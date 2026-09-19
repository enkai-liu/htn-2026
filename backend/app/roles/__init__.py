"""Importing this package registers every role factory with the orchestration registry."""
from . import actuator, advocate, conductor, critic, judge, mutator, resolver, synthesizer, verifier  # noqa: F401
from .scouts import corpus, live  # noqa: F401
