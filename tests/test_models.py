from sqlalchemy.orm import configure_mappers


def test_sqlalchemy_mappers_configure():
    from app.core import models  # noqa: F401

    configure_mappers()
