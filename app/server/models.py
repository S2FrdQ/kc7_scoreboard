import random
import string
import json
import datetime
from faker import Faker
from faker.providers import internet
from flask_security import RoleMixin, UserMixin, user_registered
from sqlalchemy import desc
# Import password / encryption helper tools
from werkzeug.security import check_password_hash, generate_password_hash
from flask import jsonify
from app import cache

# Import the database object (db) from the main application module
# We will define this inside /app/__init__.py in the next sections.
from app import db

# instantiate faker
fake = Faker()
fake.add_provider(internet)


# Define a base model for other database tables to inherit
class Base(db.Model):

    __abstract__    = True

    id              = db.Column(db.Integer, primary_key=True)

    def __init__(self, id, name, domain):

        self.id = id


##########################################################
# The following classes are specific to user autentication
###########################################################

class AuthBase(db.Model):

    __abstract__    = True
    id              = db.Column(db.Integer, primary_key=True)


class Team(AuthBase):

    __tablename__   = "teams"

    name                    = db.Column(db.String(50), nullable=False)
    score                   = db.Column(db.Integer, nullable=False)
    _mitigations            = db.Column(db.Text)
    security_awareness      = db.Column(db.Float, nullable=False)

    def __init__(self, name, score, _mitigations="", security_awareness=.25):

        self.name = name
        self.score = score
        self._mitigations = _mitigations
        self.security_awareness = security_awareness

    def __repr__(self):
        return '<Team %r>' % self.name


class Users(AuthBase, RoleMixin):

    __tablename__   = "users"
    id              = db.Column('user_id', db.Integer, primary_key=True)
    active = db.Column('is_active', db.Boolean(), nullable=False, server_default='1') 
    
    username        = db.Column('username', db.String(50), unique=True, index=True)
    pw_hash         = db.Column('pw_hash', db.String(150))
    email           = db.Column('email', db.String(50), unique=True, index=True)
    registered_on   = db.Column('registered_on', db.DateTime)

    team_id = db.Column(db.Integer, db.ForeignKey('teams.id'))
    team = db.relationship(
        'Team', backref=db.backref('members', lazy='dynamic')
    )
    
    roles = db.relationship(
        'Roles', secondary='user_roles', backref='users', lazy=True
    )

    solves = db.relationship(
        'Challenges', secondary='solves', backref="users", lazy=True
    )

    def __init__(self, username, password, email, team):
        self.username = username
        self.set_password(password)
        self.email = email
        self.registered_on = datetime.datetime.now()
        self.team = team

    def get_solves(self):
        solves = Solves.query.filter_by(user_id=self.id)
        return solves.all()

    @property
    def solves(self):
        return self.get_solves()


    @property
    def score(self):
        return self.get_score()

    @cache.memoize()
    def get_score(self, admin=False):
        score = db.func.sum(Challenges.value).label("score")
        user = (
            db.session.query(Solves.user_id, score)
            .join(Users, Solves.user_id == Users.id)
            .join(Challenges, Solves.challenge_id == Challenges.id)
            .filter(Users.id == self.id)
        )

        user = user.group_by(Solves.user_id).first()

        if user:
            return int(user.score or 0)
        else:
            return 0

    
    @cache.memoize()
    def get_place(self, admin=False, numeric=False):
        """
        This method is generally a clone of CTFd.scoreboard.get_standings.
        The point being that models.py must be self-reliant and have little
        to no imports within the CTFd application as importing from the
        application itself will result in a circular import.
        """
        from app.server.utils import get_user_standings
        from  app.server.utils import ordinalize

        standings = get_user_standings()

        for i, user in enumerate(standings):
            if user.user_id == self.id:
                n = i + 1
                if numeric:
                    return n
                ranking =  ordinalize(n)
                if ranking == "1st":
                    return ranking + "  🥇"
                elif ranking == "2nd":
                    return ranking + "  🥈"
                elif ranking == "3rd":
                    return ranking + "  🥉"
                else: 
                    return ranking
        else:
            return None

    @property
    def place(self):
        return self.get_place()

    
    def set_password(self, password):
        self.pw_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.pw_hash, password)

    def is_authenticated(self):
        return True

    def is_active(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

    def has_role(self, role):
        return role in self.get_roles()

    def get_roles(self):
        return [role.name for role in self.roles]

    def __repr__(self):
        return '<User %r>' % (self.username)


# Define the Role data-model
class Roles(AuthBase):
    __tablename__ = 'roles'
    id = db.Column(db.Integer(), primary_key=True)
    name = db.Column(db.String(50), unique=True)


# Define the UserRoles association table
class UserRoles(AuthBase):
    __tablename__ = 'user_roles'
    id = db.Column(db.Integer(), primary_key=True)
    user_id = db.Column(db.Integer(), db.ForeignKey('users.user_id', ondelete='CASCADE'))
    role_id = db.Column(db.Integer(), db.ForeignKey('roles.id', ondelete='CASCADE'))


class Report(AuthBase):

    """
        A report object is generated by company employees
        Each report belongs to a team and is generated 
        based on the security awareness of the company
    """
    __tablename__   = "report"

    subject                = db.Column(db.String(50), nullable=False)
    sender                 = db.Column(db.String(50), nullable=False)
    recipient              = db.Column(db.String(50), nullable=False)
    time                   = db.Column(db.String(50), nullable=False)
    
    team_id                = db.Column(db.Integer, db.ForeignKey('teams.id'))
    team                   = db.relationship('Team', backref=db.backref('reports', lazy='dynamic'))

    def __init__(self, subject, sender, recipient, time, team):

        self.subject = subject
        self.sender = sender
        self.recipient = recipient
        self.time = time
        self.team = team

    def __repr__(self):
        return '<Report %r>' % self.id


##########################################################
# The following classes are specific to game sessions
###########################################################

# Define the Role data-model
class GameSession(Base):
    id              = db.Column(db.Integer(), primary_key=True)
    state           = db.Column(db.Boolean)
    start_time      = db.Column(db.String(50)) #should be given as a timestamp float
    seed_date       = db.Column(db.String(50))  
    time_multiplier = db.Column(db.Integer())

    def __init__(self, state, start_time, seed_date="2022-01-01", time_multiplier=1000):
        self.state = False
        self.seed_date = seed_date    # starting date for the game
        self.start_time = start_time  # real life start time of game
        self.time_multiplier = time_multiplier


##################################################################
# The following classes are specific to scoring system for the game
##################################################################

# Class represents a question posed to to users during the walk through
# these are created by the admin and can be "solved" by other others
class Challenges(db.Model):
    __tablename__ = "challenges"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80))
    category = db.Column(db.String(80))
    description = db.Column(db.Text)
    answer = db.Column(db.String(80))
    value = db.Column(db.Integer)
    solves = db.relationship(
        "Users", secondary='solves', backref="challenges", lazy=True
    )

    def __init__(self, name:str, description:str, answer:str, category:str, value:int) -> None:
        self.name = name
        self.description = description
        self.value = value
        self.answer = answer
        self.category = category or "None"

    @property
    def solvers(self) -> "list[int]":
        return list(set([solver.user_id for solver in self.get_solvers()]))

    @property
    def solver_names(self) -> "list[str]":
        """Take a list of user_ids for solvers and returns their names"""
        return list(set([solver.username for solver in self.get_solvers()]))

    def get_solvers(self):
        return Solves.query.filter_by(challenge_id=self.id)
        
    def __repr__(self):
        return "<Challenge %r>" % self.name


# DB item is intermediarry between user and Challenger
# Create when a user answers the question correctly
# Helper table between students and courses
# Define the UserRoles association table
class Solves(Base):
    __tablename__ = 'solves'
    id                          = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    challenge_id                = db.Column(db.Integer, db.ForeignKey('challenges.id', ondelete="CASCADE"))
    user_id                     = db.Column(db.Integer, db.ForeignKey('users.user_id', ondelete="CASCADE"))
    username                   = db.Column(db.String(50))  

    def __init__(self, challenge_id:int, user_id:int, username:str="na"):
        self.challenge_id = challenge_id
        self.user_id = user_id
        self.username = username





# # Define the UserRoles association table
# class UserRoles(AuthBase):
#     __tablename__ = 'user_roles'
#     id = db.Column(db.Integer(), primary_key=True)
#     user_id = db.Column(db.Integer(), db.ForeignKey('users.user_id', ondelete='CASCADE'))
#     role_id = db.Column(db.Integer(), db.ForeignKey('roles.id', ondelete='CASCADE'))



# class Solves():
#     id = db.Column(
#         None, db.ForeignKey("solves.id", ondelete="CASCADE"), primary_key=True
#     )
#     user_id = column_property(
#         db.Column(db.Integer, db.ForeignKey("users.id", ondelete="CASCADE")),
#         Submissions.user_id,
#     )
