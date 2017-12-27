from CTFd.plugins.keys import get_key_class, KEY_CLASSES, BaseKey
from CTFd.plugins import challenges, register_plugin_assets_directory
from flask import session
from CTFd.models import db, Challenges, WrongKeys, Keys, Awards, Solves, Files, Tags
from CTFd import utils
import logging


class CTFdMultiAnswerChallenge(challenges.BaseChallenge):
    """multi-answer allows right and wrong answers and leaves the question open"""
    id = "multianswer"
    name = "multianswer"

    templates = {  # Handlebars templates used for each aspect of challenge editing & viewing
        'create': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-create.njk',
        'update': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-update.njk',
        'modal': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-modal.njk',
    }
    scripts = {  # Scripts that are loaded when a template is loaded
        'create': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-create.js',
        'update': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-update.js',
        'modal': '/plugins/CTFd-multi-answer/assets/multianswer-challenge-modal.js',
    }

    @staticmethod
    def create(request):
        """
        This method is used to process the challenge creation request.

        :param request:
        :return:
        """
        # Create challenge
        chal = MultiAnswerChallenge(
            name=request.form['name'],
            description=request.form['description'],
            value=request.form['value'],
            category=request.form['category'],
            type=request.form['chaltype']
        )

        if 'hidden' in request.form:
            chal.hidden = True
        else:
            chal.hidden = False

        max_attempts = request.form.get('max_attempts')
        if max_attempts and max_attempts.isdigit():
            chal.max_attempts = int(max_attempts)

        db.session.add(chal)
        db.session.commit()

        flag = Keys(chal.id, request.form['key'], request.form['key_type[0]'])
        if request.form.get('keydata'):
            flag.data = request.form.get('keydata')
        db.session.add(flag)

        db.session.commit()

        files = request.files.getlist('files[]')
        for f in files:
            utils.upload_file(file=f, chalid=chal.id)

        db.session.commit()

    @staticmethod
    def update(challenge, request):
        """
        This method is used to update the information associated with a challenge. This should be kept strictly to the
        Challenges table and any child tables.

        :param challenge:
        :param request:
        :return:
        """
        challenge.name = request.form['name']
        challenge.description = request.form['description']
        challenge.value = int(request.form.get('value', 0)) if request.form.get('value', 0) else 0
        challenge.max_attempts = int(request.form.get('max_attempts', 0)) if request.form.get('max_attempts', 0) else 0
        challenge.category = request.form['category']
        challenge.hidden = 'hidden' in request.form
        db.session.commit()
        db.session.close()

    @staticmethod
    def read(challenge):
        """
        This method is in used to access the data of a challenge in a format processable by the front end.

        :param challenge:
        :return: Challenge object, data dictionary to be returned to the user
        """
        challenge = MultiAnswerChallenge.query.filter_by(id=challenge.id).first()
        data = {
            'id': challenge.id,
            'name': challenge.name,
            'value': challenge.value,
            'description': challenge.description,
            'category': challenge.category,
            'hidden': challenge.hidden,
            'max_attempts': challenge.max_attempts,
            'type': challenge.type,
            'type_data': {
                'id': CTFdMultiAnswerChallenge.id,
                'name': CTFdMultiAnswerChallenge.name,
                'templates': CTFdMultiAnswerChallenge.templates,
                'scripts': CTFdMultiAnswerChallenge.scripts,
            }
        }
        return challenge, data

    @staticmethod
    def delete(challenge):
        """
        This method is used to delete the resources used by a challenge.

        :param challenge:
        :return:
        """
        # Needs to remove awards data as well
        WrongKeys.query.filter_by(chalid=challenge.id).delete()
        Solves.query.filter_by(chalid=challenge.id).delete()
        Keys.query.filter_by(chal=challenge.id).delete()
        files = Files.query.filter_by(chal=challenge.id).all()
        for f in files:
            utils.delete_file(f.id)
        Files.query.filter_by(chal=challenge.id).delete()
        Tags.query.filter_by(chal=challenge.id).delete()
        Challenges.query.filter_by(id=challenge.id).delete()
        db.session.commit()

    @staticmethod
    def attempt(chal, request):
        """
        This method is used to check whether a given input is right or wrong. It does not make any changes and should
        return a boolean for correctness and a string to be shown to the user. It is also in charge of parsing the
        user's input from the request itself.

        :param chal: The Challenge object from the database
        :param request: The request the user submitted
        :return: (boolean, string)
        """
        provided_key = request.form['key'].strip()
        chal_keys = Keys.query.filter_by(chal=chal.id).all()
        for chal_key in chal_keys:
            if get_key_class(chal_key.type).compare(chal_key.flag, provided_key):
                if chal_key.type == "correct":
                    solves = Awards.query.filter_by(teamid=session['id'], name=chal.id,
                                                    description=request.form['key'].strip()).first()
                    try:
                        flag_value = solves.description
                    except AttributeError:
                        flag_value = ""
                    # Challenge not solved yet
                    if provided_key != flag_value or not solves:
                        solve = Awards(teamid=session['id'], name=chal.id, value=chal.value)
                        solve.description = provided_key
                        db.session.add(solve)
                        db.session.commit()
                        db.session.close()
                    return True, 'Correct'
                    # TODO Add description function call to the end of "Correct" in return
                elif chal_key.type == "wrong":
                    solves = Awards.query.filter_by(teamid=session['id'], name=chal.id,
                                                    description=request.form['key'].strip()).first()
                    try:
                        flag_value = solves.description
                    except AttributeError:
                        flag_value = ""
                    # Challenge not solved yet
                    if provided_key != flag_value or not solves:
                        wrong_value = 0
                        wrong_value -= chal.value
                        wrong = WrongKeys(teamid=session['id'], chalid=chal.id, ip=utils.get_ip(request),
                                          flag=provided_key)
                        solve = Awards(teamid=session['id'], name=chal.id, value=wrong_value)
                        solve.description = provided_key
                        db.session.add(wrong)
                        db.session.add(solve)
                        db.session.commit()
                        db.session.close()
                    return False, 'Error'
                    # TODO Add description function call to the end of "Error" in return
        return False, 'Incorrect'

    @staticmethod
    def solve(team, chal, request):
        """This method is not used"""
    @staticmethod
    def fail(team, chal, request):
        """This method is not used"""


class CTFdWrongKey(BaseKey):
    """Wrong key to deduct points from the player"""
    id = 2
    name = "wrong"
    templates = {  # Handlebars templates used for key editing & viewing
        'create': '/plugins/CTFd-multi-answer/assets/create-wrong-modal.njk',
        'update': '/plugins/CTFd-multi-answer/assets/edit-wrong-modal.njk',
    }

    @staticmethod
    def compare(saved, provided):
        """Compare the saved and provided keys"""
        if len(saved) != len(provided):
            return False
        result = 0
        for x, y in zip(saved, provided):
            result |= ord(x) ^ ord(y)
        return result == 0


class CTFdCorrectKey(BaseKey):
    """Wrong key to deduct points from the player"""
    id = 3
    name = "correct"
    templates = {  # Handlebars templates used for key editing & viewing
        'create': '/plugins/CTFd-multi-answer/assets/create-correct-modal.njk',
        'update': '/plugins/CTFd-multi-answer/assets/edit-correct-modal.njk',
    }

    @staticmethod
    def compare(saved, provided):
        """Compare the saved and provided keys"""
        if len(saved) != len(provided):
            return False
        result = 0
        for x, y in zip(saved, provided):
            result |= ord(x) ^ ord(y)
        return result == 0


class MultiAnswerChallenge(Challenges):
    __mapper_args__ = {'polymorphic_identity': 'multianswer'}
    id = db.Column(None, db.ForeignKey('challenges.id'), primary_key=True)
    initial = db.Column(db.Integer)

    def __init__(self, name, description, value, category, type='multianswer'):
        self.name = name
        self.description = description
        self.value = value
        self.initial = value
        self.category = category
        self.type = type


def load(app):
    """load overrides for multianswer plugin to work properly"""
    app.db.create_all()
    register_plugin_assets_directory(app, base_path='/plugins/CTFd-multi-answer/assets/')
    challenges.CHALLENGE_CLASSES["multianswer"] = CTFdMultiAnswerChallenge
    KEY_CLASSES["wrong"] = CTFdWrongKey
    KEY_CLASSES["correct"] = CTFdCorrectKey
