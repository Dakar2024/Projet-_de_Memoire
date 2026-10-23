from piccolo.columns import JSONB, UUID, Boolean, ForeignKey, Integer, Text, Timestamptz, Varchar
from piccolo.columns.base import OnDelete
from piccolo.table import Table

from features.auth.tables import User


class Conversation(Table, tablename="conversations"):
    """A display thread: the RAG has no memory, each question is sent alone (MODELISATION § 4.2)."""

    id         = UUID(primary_key=True)
    # Erasing the account erases its history.
    user       = ForeignKey(references=User, on_delete=OnDelete.cascade, index=True)
    title      = Varchar(length=120)
    panel      = Varchar(length=16, null=True, default=None)  # null = every panel
    pinned     = Boolean(default=False)
    created_at = Timestamptz(auto_now_add=True)
    updated_at = Timestamptz(auto_now_add=True, index=True)  # last question, for the sidebar order
    # Soft delete: hidden at once, removed for good by the nightly purge.
    deleted_at = Timestamptz(null=True, default=None)


class Message(Table, tablename="messages"):
    id             = UUID(primary_key=True)
    conversation   = ForeignKey(references=Conversation, on_delete=OnDelete.cascade, index=True)
    role           = Varchar(length=16)  # user | assistant
    content        = Text()              # the question, or the answer text
    # Assistant only:
    # answered | partial | not_in_sources | out_of_scope | unverifiable
    status         = Varchar(length=32, null=True, default=None)
    scope_reason   = Varchar(length=32, null=True, default=None)
    history        = JSONB(null=True, default=None)  # list of sentences
    disclaimer     = Text(null=True, default=None)
    rag_request_id = Varchar(length=64, null=True, default=None)
    timings_ms     = JSONB(null=True, default=None)
    archive        = Varchar(length=16, null=True, default=None)  # ClinVar archive of the sources, e.g. 2026-10
    created_at     = Timestamptz()  # set by the service: the question before its answer


class MessageSource(Table, tablename="message_sources"):
    """Frozen copy of a cited record: ClinVar is reloaded monthly, the thread shows what was answered."""

    id                       = UUID(primary_key=True)
    message                  = ForeignKey(references=Message, on_delete=OnDelete.cascade, index=True)
    rank                     = Integer()  # citation order
    doc_id                   = Varchar(length=255)
    gene                     = Varchar(length=64, null=True, default=None, index=True)
    variant                  = Varchar(length=1000, null=True, default=None)
    protein                  = Varchar(length=255, null=True, default=None)
    significance             = Varchar(length=255, null=True, default=None)
    significance_fr          = Varchar(length=255, null=True, default=None)
    review_status            = Varchar(length=255, null=True, default=None)
    clinvar_variation_id     = Varchar(length=32, null=True, default=None, index=True)
    clinvar_url              = Varchar(length=500, null=True, default=None)
    archive                  = Varchar(length=16, null=True, default=None)
    previous_significance    = Varchar(length=255, null=True, default=None)
    previous_significance_fr = Varchar(length=255, null=True, default=None)
    previous_until           = Varchar(length=16, null=True, default=None)


class Feedback(Table, tablename="feedback"):
    """Useful / to improve, given by the owner of the conversation: at most one per answer."""

    id          = UUID(primary_key=True)
    message     = ForeignKey(references=Message, on_delete=OnDelete.cascade, unique=True)
    rating      = Integer()  # +1 | -1
    comment     = Text(null=True, default=None)
    status      = Varchar(length=16, default="new")  # new | reviewed
    reviewed_by = ForeignKey(references=User, null=True, default=None, on_delete=OnDelete.set_null)
    created_at  = Timestamptz(auto_now_add=True)
    updated_at  = Timestamptz(auto_now=True)
