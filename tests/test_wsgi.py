"""Tests for WSGI middleware integration."""

import threading
from typing import Any

import flask
import nplusone.ext.sqlalchemy  # noqa: F401
import pytest
import webtest
from flask_sqlalchemy import SQLAlchemy
from nplusone.core import exceptions, signals
from nplusone.ext.wsgi import NPlusOneMiddleware

from tests.utils import make_models


def _get_worker() -> str:
    return str(threading.current_thread().ident)


@pytest.fixture(scope="module", autouse=True)
def _setup() -> None:
    signals.get_worker = _get_worker  # type: ignore[assignment]


@pytest.fixture()
def db() -> SQLAlchemy:
    """Create a Flask-SQLAlchemy instance."""
    return SQLAlchemy()


@pytest.fixture()
def sa_models(db: SQLAlchemy) -> Any:
    """Create test models."""
    return make_models(db.Model)


@pytest.fixture()
def objects(db: SQLAlchemy, app: flask.Flask, sa_models: Any) -> None:
    """Populate test data."""
    hobby = sa_models.Hobby()
    address = sa_models.Address()
    user = sa_models.User(addresses=[address], hobbies=[hobby])
    db.session.add(user)
    db.session.commit()
    db.session.close()


@pytest.fixture()
def app(db: SQLAlchemy, sa_models: Any) -> Any:
    """Create and configure a Flask application."""
    flask_app = flask.Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    db.init_app(flask_app)
    with flask_app.app_context():
        db.create_all()
        yield flask_app


@pytest.fixture()
def routes(app: flask.Flask, sa_models: Any, wrapper: Any) -> None:
    """Register test routes."""

    @app.route("/many_to_one/")
    def many_to_one() -> str:
        users = sa_models.User.query.all()
        return str(users[0].addresses)

    @app.route("/many_to_one_one/")
    def many_to_one_one() -> str:
        user = sa_models.User.query.filter_by(id=1).one()
        return str(user.addresses)


@pytest.fixture()
def wrapper(app: flask.Flask) -> NPlusOneMiddleware:
    """Create the WSGI middleware wrapper."""
    return NPlusOneMiddleware(app)


@pytest.fixture()
def client(routes: None, wrapper: NPlusOneMiddleware) -> webtest.TestApp:
    """Create a test client."""
    return webtest.TestApp(wrapper)


class TestNPlusOneMiddleware:
    """Tests for the WSGI N+1 middleware."""

    def test_many_to_one(self, objects: Any, client: webtest.TestApp) -> None:
        with pytest.raises(exceptions.NPlusOneError):
            client.get("/many_to_one/")

    def test_many_to_one_one(self, objects: Any, client: webtest.TestApp) -> None:
        client.get("/many_to_one_one/")
