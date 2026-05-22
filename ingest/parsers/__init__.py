"""Honeypot event parsers."""
from meli.ingest.parsers.cowrie import CowrieParser
from meli.ingest.parsers.heralding import HeraldingParser
from meli.ingest.parsers.dionaea import DionaeaParser
from meli.ingest.parsers.http_honeypot import HttpHoneypotParser
from meli.ingest.parsers.glastopf import GlastopfParser
from meli.ingest.parsers.mailoney import MaloneyParser
from meli.ingest.parsers.generic_json import GenericJsonParser

PARSER_MAP = {
    "cowrie": CowrieParser,
    "heralding": HeraldingParser,
    "dionaea": DionaeaParser,
    "http": HttpHoneypotParser,
    "glastopf": GlastopfParser,
    "mailoney": MaloneyParser,
    "generic_json": GenericJsonParser,
}


def get_parser(honeypot_type: str):
    cls = PARSER_MAP.get(honeypot_type.lower(), GenericJsonParser)
    return cls()
