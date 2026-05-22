"""Tests for Flask-SQLAlchemy integration."""

from typing import Any
from unittest import mock

import flask
import pytest
import sqlalchemy as sa
import webtest
from flask_sqlalchemy import SQLAlchemy
from nplusone.core import exceptions
from nplusone.ext.flask_sqlalchemy import NPlusOne, setup_state

from tests.utils import make_models


@pytest.fixture(scope="module", autouse=True)
def _setup() -> None:
    setup_state()


@pytest.fixture()
def db() -> SQLAlchemy:
    """Create a Flask-SQLAlchemy instance."""
    return SQLAlchemy()


@pytest.fixture()
def sa_models(db: SQLAlchemy) -> Any:
    """Create test models on the Flask-SQLAlchemy base."""
    return make_models(db.Model)


@pytest.fixture()
def objects(db: SQLAlchemy, app: flask.Flask, sa_models: Any) -> None:
    """Populate the database with test data."""
    hobby = sa_models.Hobby()
    address = sa_models.Address()
    user = sa_models.User(addresses=[address], hobbies=[hobby])
    db.session.add(user)
    db.session.commit()
    db.session.close()


@pytest.fixture()
def logger() -> mock.Mock:
    """Create a mock logger."""
    return mock.Mock()


@pytest.fixture()
def app(db: SQLAlchemy, sa_models: Any, logger: mock.Mock) -> Any:
    """Create and configure a Flask application."""
    flask_app = flask.Flask(__name__)
    flask_app.config["TESTING"] = True
    flask_app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    flask_app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    flask_app.config["NPLUSONE_LOGGER"] = logger
    db.init_app(flask_app)
    with flask_app.app_context():
        db.create_all()
        yield flask_app


@pytest.fixture()
def wrapper(app: flask.Flask) -> NPlusOne:
    """Create and register the NPlusOne extension."""
    return NPlusOne(app)


@pytest.fixture()
def routes(app: flask.Flask, sa_models: Any, wrapper: NPlusOne) -> None:
    """Register test routes."""

    @app.route("/many_to_one/")
    def many_to_one() -> str:
        users = sa_models.User.query.all()
        return str(users[0].addresses)

    @app.route("/many_to_one_one/")
    def many_to_one_one() -> str:
        user = sa_models.User.query.filter_by(id=1).one()
        return str(user.addresses)

    @app.route("/many_to_one_first/")
    def many_to_one_first() -> str:
        user = sa_models.User.query.first()
        return str(user.addresses)

    @app.route("/many_to_one_ignore/")
    def many_to_one_ignore() -> str:
        with wrapper.ignore("lazy_load"):
            users = sa_models.User.query.all()
            return str(users[0].addresses)

    @app.route("/many_to_many/")
    def many_to_many() -> str:
        users = sa_models.User.query.all()
        return str(users[0].hobbies)

    @app.route("/many_to_many_impossible/")
    def many_to_many_impossible() -> str:
        user = sa_models.User.query.first()
        sa_models.User.query.all()
        return str(user.hobbies)

    @app.route("/many_to_many_impossible_one/")
    def many_to_many_impossible_one() -> str:
        user = sa_models.User.query.one()
        sa_models.User.query.all()
        return str(user.hobbies)

    @app.route("/eager_join/")
    def eager_join() -> str:
        users = sa_models.User.query.options(
            sa.orm.subqueryload(sa_models.User.hobbies)
        ).all()
        return str(users[0].hobbies if users else None)

    @app.route("/eager_subquery/")
    def eager_subquery() -> str:
        users = sa_models.User.query.options(
            sa.orm.subqueryload(sa_models.User.hobbies)
        ).all()
        print(sa_models.User.hobbies)
        return str(users[0].hobbies if users else None)

    @app.route("/eager_join_unused/")
    def eager_join_unused() -> str:
        users = sa_models.User.query.options(
            sa.orm.joinedload(sa_models.User.hobbies)
        ).all()
        return str(users[0])

    @app.route("/eager_subquery_unused/")
    def eager_subquery_unused() -> str:
        users = sa_models.User.query.options(
            sa.orm.subqueryload(sa_models.User.hobbies)
        ).all()
        return str(users[0])

    @app.route("/eager_nested/")
    def eager_nested() -> str:
        hobbies = sa_models.Hobby.query.options(
            sa.orm.joinedload(sa_models.Hobby.users).joinedload(
                sa_models.User.addresses,
            )
        ).all()
        return str(hobbies[0].users[0].addresses)

    @app.route("/eager_nested_unused/")
    def eager_nested_unused() -> str:
        hobbies = sa_models.Hobby.query.options(
            sa.orm.joinedload(sa_models.Hobby.users).joinedload(
                sa_models.User.addresses,
            )
        ).all()
        return str(hobbies[0])


@pytest.fixture()
def client(app: flask.Flask, routes: None, wrapper: NPlusOne) -> webtest.TestApp:
    """Create a test client."""
    return webtest.TestApp(app)


class TestNPlusOne:
    """Tests for Flask-SQLAlchemy N+1 detection."""

    def test_many_to_one(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/many_to_one/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "User.addresses" in args[1]

    def test_many_to_one_one(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/many_to_one_one/")
        assert not logger.log.called

    def test_many_to_one_first(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/many_to_one_first/")
        assert not logger.log.called

    def test_many_to_one_ignore(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/many_to_one_ignore/")
        assert not logger.log.called

    def test_many_to_many(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/many_to_many/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "User.hobbies" in args[1]

    def test_many_to_many_impossible(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/many_to_many_impossible/")
        assert not logger.log.called

    def test_many_to_many_impossible_one(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/many_to_many_impossible_one/")
        assert not logger.log.called

    def test_eager_join(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/eager_join/")
        assert not logger.log.called

    def test_eager_subquery(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/eager_subquery/")
        assert not logger.log.called

    def test_eager_join_empty(
        self,
        sa_models: Any,
        objects: Any,
        client: webtest.TestApp,
        logger: mock.Mock,
    ) -> None:
        sa_models.User.query.delete()
        client.get("/eager_join/")
        assert not logger.log.called

    def test_eager_subquery_empty(
        self,
        sa_models: Any,
        objects: Any,
        client: webtest.TestApp,
        logger: mock.Mock,
    ) -> None:
        sa_models.User.query.delete()
        client.get("/eager_subquery/")
        assert not logger.log.called

    def test_eager_join_unused(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/eager_join_unused/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "User.hobbies" in args[1]

    def test_eager_subquery_unused(
        self, objects: Any, client: webtest.TestApp, logger: mock.Mock
    ) -> None:
        client.get("/eager_subquery_unused/")
        assert len(logger.log.call_args_list) == 1
        args = logger.log.call_args[0]
        assert "User.hobbies" in args[1]

    def test_eager_nested(
        self,
        app: flask.Flask,
        wrapper: NPlusOne,
        objects: Any,
        client: webtest.TestApp,
        logger: mock.Mock,
    ) -> None:
        client.get("/eager_nested/")
        assert not logger.log.called

    def test_eager_nested_unused(
        self,
        app: flask.Flask,
        wrapper: NPlusOne,
        objects: Any,
        client: webtest.TestApp,
        logger: mock.Mock,
    ) -> None:
        client.get("/eager_nested_unused/")
        assert len(logger.log.call_args_list) == 2
        calls = [call[0] for call in logger.log.call_args_list]
        assert any("Hobby.users" in call[1] for call in calls)
        assert any("User.addresses" in call[1] for call in calls)

    def test_many_to_many_raise(
        self,
        app: flask.Flask,
        wrapper: NPlusOne,
        objects: Any,
        client: webtest.TestApp,
        logger: mock.Mock,
    ) -> None:
        app.config["NPLUSONE_RAISE"] = True
        with pytest.raises(exceptions.NPlusOneError):
            client.get("/many_to_many/")

    def test_many_to_many_whitelist(
        self,
        app: flask.Flask,
        wrapper: NPlusOne,
        objects: Any,
        client: webtest.TestApp,
        logger: mock.Mock,
    ) -> None:
        app.config["NPLUSONE_WHITELIST"] = [{"model": "User"}]
        client.get("/many_to_many/")
        assert not logger.log.called

    def test_many_to_many_whitelist_wildcard(
        self,
        app: flask.Flask,
        wrapper: NPlusOne,
        objects: Any,
        client: webtest.TestApp,
        logger: mock.Mock,
    ) -> None:
        app.config["NPLUSONE_WHITELIST"] = [{"model": "U*r"}]
        client.get("/many_to_many/")
        assert not logger.log.called

    def test_many_to_many_whitelist_decoy(
        self,
        app: flask.Flask,
        wrapper: NPlusOne,
        objects: Any,
        client: webtest.TestApp,
        logger: mock.Mock,
    ) -> None:
        app.config["NPLUSONE_WHITELIST"] = [{"model": "Hobby"}]
        client.get("/many_to_many/")
        assert logger.log.called
