from typing import Annotated

from pydantic import StringConstraints


SESSION_ID_MAX_LENGTH = 100
SessionId = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=SESSION_ID_MAX_LENGTH,
    ),
]
