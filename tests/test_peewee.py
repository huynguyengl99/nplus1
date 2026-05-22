"""Tests for Peewee integration."""

from typing import Any

import nplusone.ext.peewee  # noqa: F401
import peewee as pw
import pytest
from nplusone.core import signals

from tests.utils import Bunch


@pytest.fixture()
def db() -> pw.SqliteDatabase:
    """Create an in-memory SQLite database."""
    return pw.SqliteDatabase(":memory:")


@pytest.fixture()
def base(db: pw.SqliteDatabase) -> type:
    """Create a Peewee base model class."""

    class Base(pw.Model):
        class Meta:
            database = db

    return Base


@pytest.fixture()
def peewee_models(base: type) -> Bunch:
    """Create Peewee test models."""

    class Hobby(base):  # type: ignore[misc]
        pass

    class User(base):  # type: ignore[misc]
        hobbies = pw.ManyToManyField(Hobby, backref="users")

    class Address(base):  # type: ignore[misc]
        user = pw.ForeignKeyField(User, backref="addresses")

    return Bunch(
        Hobby=Hobby,
        User=User,
        Address=Address,
    )


@pytest.fixture()
def peewee_session(db: pw.SqliteDatabase, peewee_models: Bunch) -> Any:
    """Create tables and return a transaction."""
    db.create_tables(
        [
            peewee_models.User,
            peewee_models.Address,
            peewee_models.Hobby,
            peewee_models.User.hobbies.get_through_model(),
        ],
        safe=True,
    )
    with db.atomic() as transaction:
        yield transaction


@pytest.fixture()
def peewee_objects(peewee_models: Bunch, peewee_session: Any) -> Bunch:
    """Populate test data."""
    user = peewee_models.User.create(id=1)
    hobby = peewee_models.Hobby.create(id=1)
    hobby.users.add(user)
    address = peewee_models.Address.create(id=1, user=user)
    return Bunch(
        user=user,
        hobby=hobby,
        address=address,
    )


class TestManyToOne:
    """Tests for Peewee many-to-one detection."""

    def test_many_to_one(
        self,
        peewee_models: Bunch,
        peewee_session: Any,
        peewee_objects: Bunch,
        calls: Any,
        lazy_listener: Any,
    ) -> None:
        users = peewee_models.User.select()
        list(users[0].addresses)
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (peewee_models.User, "User:1", "addresses")

    def test_many_to_one_get(
        self,
        peewee_models: Bunch,
        peewee_session: Any,
        peewee_objects: Bunch,
        calls: Any,
        lazy_listener: Any,
    ) -> None:
        user = peewee_models.User.get()
        list(user.addresses)
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (peewee_models.User, "User:1", "addresses")
        assert not lazy_listener.parent.notify.called

    def test_many_to_one_prefetch(
        self,
        peewee_models: Bunch,
        peewee_session: Any,
        peewee_objects: Bunch,
        calls: Any,
        lazy_listener: Any,
    ) -> None:
        users = pw.prefetch(
            peewee_models.User.select(),
            peewee_models.Address.select(),
        )
        list(users[0].addresses)
        assert len(calls) == 0

    def test_many_to_one_ignore(
        self,
        peewee_models: Bunch,
        peewee_session: Any,
        peewee_objects: Bunch,
        calls: Any,
    ) -> None:
        user = peewee_models.User.select().first()
        with signals.ignore(signals.lazy_load):
            user.addresses
        assert len(calls) == 0

    def test_many_to_one_reverse(
        self,
        peewee_models: Bunch,
        peewee_session: Any,
        peewee_objects: Bunch,
        calls: Any,
    ) -> None:
        address = peewee_models.Address.select().first()
        address.user
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (peewee_models.Address, "Address:1", "user")

    def test_many_to_one_reverse_join(
        self,
        peewee_models: Bunch,
        peewee_session: Any,
        peewee_objects: Bunch,
        calls: Any,
    ) -> None:
        address = (
            peewee_models.Address.select(
                peewee_models.Address,
                peewee_models.User,
            )
            .join(peewee_models.User)
            .first()
        )
        address.user
        assert len(calls) == 0

    def test_many_to_one_reverse_prefetch(
        self,
        peewee_models: Bunch,
        peewee_session: Any,
        peewee_objects: Bunch,
        calls: Any,
    ) -> None:
        addresses = pw.prefetch(
            peewee_models.Address.select(),
            peewee_models.User.select(),
        )
        addresses[0].user
        assert len(calls) == 0


class TestManyToMany:
    """Tests for Peewee many-to-many detection."""

    def test_many_to_many(
        self,
        peewee_models: Bunch,
        peewee_session: Any,
        peewee_objects: Bunch,
        calls: Any,
    ) -> None:
        users = peewee_models.User.select()
        list(users[0].hobbies)
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (peewee_models.User, "User:1", "hobbies")

    def test_many_to_many_reverse(
        self,
        peewee_models: Bunch,
        peewee_session: Any,
        peewee_objects: Bunch,
        calls: Any,
    ) -> None:
        hobby = peewee_models.Hobby.select().first()
        list(hobby.users)
        assert len(calls) == 1
        call = calls[0]
        assert call.objects == (peewee_models.Hobby, "Hobby:1", "users")
