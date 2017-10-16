from CTFd.plugins.keys import get_key_class, KEY_CLASSES, BaseKey
from CTFd.plugins import challenges, register_plugin_assets_directory
from flask import request, redirect, jsonify, url_for, session, abort
from CTFd.models import db, Challenges, WrongKeys, Keys, Teams, Awards, Solves
from CTFd import utils
import logging
import time
from CTFd.plugins.challenges import get_chal_class


class MultiAnswer(challenges.BaseChallenge):
    """multianswer allows right and wrong answers and leaves the question open"""
    id = "multianswer"
    name = "multianswer"

    templates = {  # Handlebars templates used for each aspect of challenge editing & viewing
        'create': '/plugins/multianswer/assets/multianswer-challenge-create.hbs',
        'update': '/plugins/multianswer/assets/multianswer-challenge-update.hbs',
        'modal': '/plugins/multianswer/assets/multianswer-challenge-modal.hbs',
    }
    scripts = {  # Scripts that are loaded when a template is loaded
        'create': '/plugins/multianswer/assets/multianswer-challenge-create.js',
        'update': '/plugins/multianswer/assets/multianswer-challenge-update.js',
        'modal': '/plugins/multianswer/assets/multianswer-challenge-modal.js',
    }

    def attempt(chal, request):
        """Attempt the user answer to see if it's right"""
        provided_key = request.form['key'].strip()
        chal_keys = Keys.query.filter_by(chal=chal.id).all()
        for chal_key in chal_keys:
            if get_key_class(chal_key.key_type).compare(chal_key.flag, provided_key):
                if chal_key.key_type == "static":
                    return True, 'Correct'
                elif chal_key.key_type == "CTFdWrongKey":
                    return False, 'Failed Attempt'
        return False, 'Incorrect'
    @staticmethod
    def solve(team, chal, request):
        """Solve the question and put results in the Awards DB"""
        provided_key = request.form['key'].strip()
        solve = Awards(teamid=team.id, name=chal.id, value=chal.value)
        solve.description = provided_key
        db.session.add(solve)
        db.session.commit()
        db.session.close()

    @staticmethod
    def fail(team, chal, request):
        """Standard fail if the question is wrong record it"""
        provided_key = request.form['key'].strip()
        wrong = WrongKeys(teamid=team.id, chalid=chal.id, ip=utils.get_ip(request), flag=provided_key)
        db.session.add(wrong)
        db.session.commit()
        db.session.close()

    def wrong(team, chal, request):
        """Fail if the question is wrong record it and record the wrong answer to deduct points"""
        provided_key = request.form['key'].strip()
        wrong_value = 0
        wrong_value -= chal.value
        wrong = WrongKeys(teamid=team.id, chalid=chal.id, ip=utils.get_ip(request), flag=provided_key)
        solve = Awards(teamid=team.id, name=chal.id, value=wrong_value)
        solve.description = provided_key
        db.session.add(wrong)
        db.session.add(solve)
        db.session.commit()
        db.session.close()


class CTFdWrongKey(BaseKey):
    """Wrong key to deduct points from the player"""
    id = 2
    name = "CTFdWrongKey"
    templates = {  # Handlebars templates used for key editing & viewing
        'create': '/plugins/multianswer/assets/CTFdWrongKey.hbs',
        'update': '/plugins/multianswer/assets/edit-CTFdWrongKey-modal.hbs',
    }

    def compare(saved, provided):
        """Compare the saved and provided keys"""
        if len(saved) != len(provided):
            return False
        result = 0
        for x, y in zip(saved, provided):
            result |= ord(x) ^ ord(y)
        return result == 0


def chal(chalid):
    """Custom chal function to override challenges.chal when multianswer is used"""
    if utils.ctf_ended() and not utils.view_after_ctf():
        abort(403)
    if not utils.user_can_view_challenges():
        return redirect(url_for('auth.login', next=request.path))
    if (utils.authed() and utils.is_verified() and (utils.ctf_started() or utils.view_after_ctf())) or utils.is_admin():
        team = Teams.query.filter_by(id=session['id']).first()
        fails = WrongKeys.query.filter_by(teamid=session['id'], chalid=chalid).count()
        logger = logging.getLogger('keys')
        data = (time.strftime("%m/%d/%Y %X"), session['username'].encode('utf-8'), request.form['key'].encode('utf-8'), utils.get_kpm(session['id']))
        print("[{0}] {1} submitted {2} with kpm {3}".format(*data))

        chal = Challenges.query.filter_by(id=chalid).first_or_404()
        chal_class = get_chal_class(chal.type)

        # Anti-bruteforce / submitting keys too quickly
        if utils.get_kpm(session['id']) > 10:
            if utils.ctftime():
                chal_class.fail(team=team, chal=chal, request=request)
            logger.warning("[{0}] {1} submitted {2} with kpm {3} [TOO FAST]".format(*data))
            # return '3' # Submitting too fast
            return jsonify({'status': 3, 'message': "You're submitting keys too fast. Slow down."})

        solves = Awards.query.filter_by(teamid=session['id'], name=chalid,
                                        description=request.form['key'].strip()).first()
        try:
            flag_value = solves.description
        except AttributeError:
            flag_value = ""
        # Challange not solved yet
        if request.form['key'].strip() != flag_value or not solves:
            chal = Challenges.query.filter_by(id=chalid).first_or_404()
            provided_key = request.form['key'].strip()
            saved_keys = Keys.query.filter_by(chal=chal.id).all()

            # Hit max attempts
            max_tries = chal.max_attempts
            if max_tries and fails >= max_tries > 0:
                return jsonify({
                    'status': 0,
                    'message': "You have 0 tries remaining"
                })

            status, message = chal_class.attempt(chal, request)
            if status:  # The challenge plugin says the input is right
                if utils.ctftime() or utils.is_admin():
                    chal_class.solve(team=team, chal=chal, request=request)
                logger.info("[{0}] {1} submitted {2} with kpm {3} [CORRECT]".format(*data))
                return jsonify({'status': 1, 'message': message})
            elif message == "Failed Attempt":
                if utils.ctftime() or utils.is_admin():
                    chal_class.wrong(team=team, chal=chal, request=request)
                logger.info("[{0}] {1} submitted {2} with kpm {3} [Failed Attempt]".format(*data))
                return jsonify({'status': 1, 'message': message})
            else:  # The challenge plugin says the input is wrong
                if utils.ctftime() or utils.is_admin():
                    chal_class.fail(team=team, chal=chal, request=request)
                logger.info("[{0}] {1} submitted {2} with kpm {3} [WRONG]".format(*data))
                # return '0' # key was wrong
                if max_tries:
                    attempts_left = max_tries - fails - 1  # Off by one since fails has changed since it was gotten
                    tries_str = 'tries'
                    if attempts_left == 1:
                        tries_str = 'try'
                    if message[-1] not in '!().;?[]\{\}':  # Add a punctuation mark if there isn't one
                        message = message + '.'
                    return jsonify({'status': 0, 'message': '{} You have {} {} remaining.'.format(message, attempts_left, tries_str)})
                else:
                    return jsonify({'status': 0, 'message': message})

        # Challenge already solved
        else:
            logger.info("{0} submitted {1} with kpm {2} [ALREADY SOLVED]".format(*data))
            # return '2' # challenge was already solved
            return jsonify({'status': 2, 'message': 'You already solved this'})
    else:
        return jsonify({
            'status': -1,
            'message': "You must be logged in to solve a challenge"
        })

def open_multihtml():
    with open('CTFd/plugins/multianswer/assets/multiteam.html') as multiteam:
        multiteam_string = str(multiteam.read())
    multiteam.close()
    return multiteam_string



def load(app):
    """load overrides for multianswer plugin to work properly"""
    register_plugin_assets_directory(app, base_path='/plugins/multianswer/assets/')
    utils.override_template('team.html', open_multihtml())
    challenges.CHALLENGE_CLASSES["multianswer"] = MultiAnswer
    KEY_CLASSES["CTFdWrongKey"] = CTFdWrongKey
    app.view_functions['challenges.chal'] = chal
