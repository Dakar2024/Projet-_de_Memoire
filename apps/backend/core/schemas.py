from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base of every request/response schema: snake_case in Python, camelCase on the wire.

    Output uses the aliases only because the app registers `PydanticPlugin(prefer_alias=True)`;
    without it Litestar serializes field names. Input accepts both spellings.
    """

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)
