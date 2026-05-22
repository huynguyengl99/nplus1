"""Shared test utilities."""

from typing import Any


class Bunch:
    """Simple attribute-based namespace for test models."""

    def __init__(self, **kwargs: Any) -> None:
        self.__dict__.update(kwargs)


def make_models(base: type) -> Bunch:
    """Create SQLAlchemy test models on the given base class."""
    import sqlalchemy as sa

    users_hobbies = sa.Table(
        "users_hobbies",
        base.metadata,  # type: ignore[attr-defined]
        sa.Column("user_id", sa.Integer, sa.ForeignKey("user.user_id")),
        sa.Column("hobby_id", sa.Integer, sa.ForeignKey("hobby.id")),
    )

    class User(base):  # type: ignore[misc]
        __tablename__ = "user"
        id = sa.Column("user_id", sa.Integer, primary_key=True)
        addresses = sa.orm.relationship("Address", backref="user")
        hobbies = sa.orm.relationship("Hobby", secondary=users_hobbies, backref="users")

    class Address(base):  # type: ignore[misc]
        __tablename__ = "address"
        id = sa.Column(sa.Integer, primary_key=True)
        user_id = sa.Column(sa.Integer, sa.ForeignKey("user.user_id"))

    class Hobby(base):  # type: ignore[misc]
        __tablename__ = "hobby"
        id = sa.Column(sa.Integer, primary_key=True)

    return Bunch(
        User=User,
        Address=Address,
        Hobby=Hobby,
    )
