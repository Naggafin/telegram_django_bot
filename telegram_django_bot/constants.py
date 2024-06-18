from enum import Enum


class ChatActions(Enum):
	message = "message"


WRITE_MESSAGE_VARIANT_SYMBOLS = "!WMVS!"
NONE_VARIANT_SYMBOLS = "!NoneNULL!"
GO_NEXT_MULTICHOICE_SYMBOLS = "!GNMS!"
ARGS_SEPARATOR_SYMBOL = "&"
