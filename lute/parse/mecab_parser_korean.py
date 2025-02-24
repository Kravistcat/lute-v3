"""
Parsing using MeCab.

Uses natto-py (https://github.com/buruzaemon/natto-py) package and
MeCab to do parsing.

Includes classes:

- KoreanParser

"""

from io import StringIO
import sys
import os
import re
from typing import List
from natto import MeCab
import mecab_ko_dic
import jaconv
from lute.parse.base import ParsedToken, AbstractParser
from lute.models.setting import UserSetting, MissingUserSettingKeyException


class KoreanParser(AbstractParser):
    """
    Korean parser.

    This is only supported if mecab is installed.

    The parser uses natto-py library, and so should
    be able to find mecab automatically; if it can't,
    you may need to set the MECAB_PATH env variable,
    managed by UserSetting.set_value("mecab_path", p)
    """

    _is_supported = None
    _old_mecab_path = None

    @classmethod
    def is_supported(cls):
        """
        True if a natto MeCab can be instantiated,
        otherwise false.
        """
        mecab_path = os.environ.get("MECAB_PATH", "<NOTSET>")
        if (
            mecab_path == KoreanParser._old_mecab_path
        ) and KoreanParser._is_supported is not None:
            return KoreanParser._is_supported

        b = False

        # Calling MeCab() prints to stderr even if the
        # exception is caught.  Suppress that output noise.
        temp_err = StringIO()
        try:
            sys.stderr = temp_err
            MeCab()
            b = True
        except:  # pylint: disable=bare-except
            b = False
        finally:
            sys.stderr = sys.__stderr__

        KoreanParser._old_mecab_path = mecab_path
        KoreanParser._is_supported = b
        return b

    @classmethod
    def name(cls):
        return "Korean"

    def get_parsed_tokens(self, text: str, language) -> List[ParsedToken]:
        "Parse the string using MeCab."
        text = re.sub(r"[ \t]+", " ", text).strip()
        text = text.replace(" ", "_")
        
        lines = []
        
        dic_dir = mecab_ko_dic.DICDIR
        
        # If the string contains a "\n", MeCab appears to silently
        # remove it.  Splitting it works (ref test_KoreanParser).
        # Flags: ref https://github.com/buruzaemon/natto-py:
        #    -F = node format
        #    -U = unknown format
        #    -E = EOP format
        with MeCab(r"-F %m\t%t\t%h\n -U %m\t%t\t%h\n -E EOP\t3\t7\n --dicdir="+dic_dir) as nm:
            for para in text.split("\n"):
                for n in nm.parse(para, as_nodes=True):
                    lines.append(n.feature)

        lines = [
            n.strip().split("\t") for n in lines if n is not None and n.strip() != ""
        ]

        # Production bug: JP parsing with MeCab would sometimes return a line
        # "0\t4" before an end-of-paragraph "EOP\t3\t7", reasons unknown.  These
        # "0\t4" tokens don't have any function, and cause problems in subsequent
        # steps of the processing in line_to_token(), so just remove them.
        lines = [n for n in lines if len(n) == 3]

        def line_to_token(lin):
            "Convert parsed line to a ParsedToken."
            term, node_type, third = lin
            is_eos = term in language.regexp_split_sentences
            if term == "EOP" and third == "7":
                term = "¶"
            is_word = node_type in "2678"
            term = term.replace("_", " ")
            return ParsedToken(term, is_word, is_eos or term == "¶")

        tokens = [line_to_token(lin) for lin in lines]
        return tokens

    def get_reading(self, text: str):
       return None
