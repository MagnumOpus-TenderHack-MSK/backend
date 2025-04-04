from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.ext.declarative import declared_attr


class CustomBase:
    @declared_attr
    def __tablename__(cls):
        return cls.__name__.lower()



# Create the base class for all models
Base = declarative_base(cls=CustomBase)