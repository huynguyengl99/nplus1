"""Tests for SQLAlchemy integration."""

from typing import Any

import nplusone.ext.sqlalchemy  # noqa: F401
import pytest
import sqlalchemy as sa
from nplusone.core import exceptions, profiler, signals
from sqlalchemy.orm import DeclarativeBase

from tests.utils import make_models


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for test models."""


models = make_models(Base)


@pytest.fixture()
def session() -> Any:
    """Create an in-memory SQLite session with test tables."""
    engine = sa.create_engine("sqlite:///:memory:")
    session_factory = sa.orm.sessionmaker(bind=engine)
    Base.metadata.create_all(bind=engine)
    return session_factory()


@pytest.fixture()
def objects(session: Any) -> None:
    """Populate the database with test data."""
    hobby = models.Hobby()
    address = models.Address()
    user = models.User(addresses=[address], hobbies=[hobby])
    session.add(user)
    session.commit()
    session.close()


class TestManyToOne:
    """Tests for many-to-one relationship detection."""

    def test_many_to_one(self, session: Any, objects: Any, calls: Any) -> None:
        users = session.query(models.User).all()
        users[0].addresses
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.User, "User:1", "addresses")

    def test_many_to_one_ignore(self, session: Any, objects: Any, calls: Any) -> None:
        users = session.query(models.User).all()
        with signals.ignore(signals.lazy_load):
            users[0].addresses
        assert len(calls) == 0

    def test_many_to_one_subquery(self, session: Any, objects: Any, calls: Any) -> None:
        users = (
            session.query(models.User)
            .options(sa.orm.subqueryload(models.User.addresses))
            .all()
        )
        users[0].addresses
        assert len(calls) == 0

    def test_many_to_one_joined(self, session: Any, objects: Any, calls: Any) -> None:
        users = (
            session.query(models.User)
            .options(sa.orm.joinedload(models.User.addresses))
            .all()
        )
        users[0].addresses
        assert len(calls) == 0

    def test_many_to_one_reverse(self, session: Any, objects: Any, calls: Any) -> None:
        addresses = session.query(models.Address).all()
        addresses[0].user
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.Address, "Address:1", "user")

    def test_many_to_one_reverse_subquery(
        self, session: Any, objects: Any, calls: Any
    ) -> None:
        addresses = (
            session.query(models.Address)
            .options(sa.orm.subqueryload(models.Address.user))
            .all()
        )
        addresses[0].user
        assert len(calls) == 0

    def test_many_to_one_reverse_joined(
        self, session: Any, objects: Any, calls: Any
    ) -> None:
        address = (
            session.query(models.Address)
            .options(sa.orm.joinedload(models.Address.user))
            .first()
        )
        address.user
        assert len(calls) == 0


class TestManyToMany:
    """Tests for many-to-many relationship detection."""

    def test_many_to_many(self, session: Any, objects: Any, calls: Any) -> None:
        users = session.query(models.User).all()
        users[0].hobbies
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.User, "User:1", "hobbies")

    def test_many_to_many_subquery(
        self, session: Any, objects: Any, calls: Any
    ) -> None:
        user = (
            session.query(models.User)
            .options(sa.orm.subqueryload(models.User.hobbies))
            .first()
        )
        user.hobbies
        assert len(calls) == 0

    def test_many_to_many_joined(self, session: Any, objects: Any, calls: Any) -> None:
        user = (
            session.query(models.User)
            .options(sa.orm.joinedload(models.User.hobbies))
            .first()
        )
        user.hobbies
        assert len(calls) == 0

    def test_many_to_many_reverse(self, session: Any, objects: Any, calls: Any) -> None:
        hobbies = session.query(models.Hobby).all()
        hobbies[0].users
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (models.Hobby, "Hobby:1", "users")

    def test_many_to_many_reverse_subquery(
        self, session: Any, objects: Any, calls: Any
    ) -> None:
        hobby = (
            session.query(models.Hobby)
            .options(sa.orm.subqueryload(models.Hobby.users))
            .first()
        )
        hobby.users
        assert len(calls) == 0

    def test_many_to_many_reverse_joined(
        self, session: Any, objects: Any, calls: Any
    ) -> None:
        hobby = (
            session.query(models.Hobby)
            .options(sa.orm.joinedload(models.Hobby.users))
            .first()
        )
        hobby.users
        assert len(calls) == 0


def test_non_orm_query(session: Any, objects: Any, lazy_listener: Any) -> None:
    """Non-ORM queries should not cause errors."""
    session.query(models.Address.id).all()


class TestProfile:
    """Tests for standalone profiler with SQLAlchemy."""

    def test_profile(self, session: Any, objects: Any) -> None:
        with profiler.Profiler():
            users = session.query(models.User).all()
            with pytest.raises(exceptions.NPlusOneError):
                users[0].addresses

    def test_profile_whitelist(self, session: Any, objects: Any) -> None:
        with profiler.Profiler(whitelist=[{"model": "User"}]):
            users = session.query(models.User).all()
            users[0].addresses
