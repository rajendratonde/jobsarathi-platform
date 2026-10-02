"""The reference lists this service manages, described as data.

Each list names its model, the extra fields beyond code/name/name_hi/sort_order/is_active,
and an optional parent list (cities -> states, job_roles -> job_categories). The API, the
approval handlers and the admin UI are all driven from this registry.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from reference_service.models import (
    City,
    EducationLevel,
    ExperienceBand,
    Industry,
    JobCategory,
    JobRole,
    JobType,
    LookupValue,
    PayType,
    Skill,
    State,
    WorkMode,
)


@dataclass(frozen=True)
class ExtraField:
    name: str            # API field name
    label: str
    kind: str            # "int" | "parent" | "text"
    required: bool = False
    immutable: bool = False


@dataclass(frozen=True)
class Parent:
    list_key: str        # parent list
    column: str          # FK column on the child, e.g. state_id
    field: str           # API field carrying the parent's code, e.g. state_code
    required: bool


@dataclass(frozen=True)
class ReferenceListDef:
    key: str
    label: str
    model: type
    extras: tuple[ExtraField, ...] = ()
    parent: Parent | None = None
    searchable: bool = False
    public: bool = True                      # exposed at /v1/reference/{key}
    columns: tuple[str, ...] = field(default=())  # model columns behind non-parent extras

    @property
    def entity_type(self) -> str:
        """approval_policies.entity_type for this list."""
        return self.key.upper()


def _list(key: str, label: str, model: type, *extras: ExtraField, parent: Parent | None = None,
          searchable: bool = False, public: bool = True) -> ReferenceListDef:
    columns = tuple(e.name for e in extras if e.kind != "parent")
    return ReferenceListDef(key, label, model, extras, parent, searchable, public, columns)


LISTS: dict[str, ReferenceListDef] = {d.key: d for d in (
    _list("states", "States", State),
    _list("cities", "Cities", City, ExtraField("state_code", "State", "parent", required=True),
          parent=Parent("states", "state_id", "state_code", required=True)),
    _list("industries", "Industries", Industry),
    _list("job_categories", "Job categories", JobCategory),
    _list("job_roles", "Job roles", JobRole, ExtraField("job_category_code", "Job category", "parent"),
          parent=Parent("job_categories", "job_category_id", "job_category_code", required=False)),
    _list("skills", "Skills", Skill, searchable=True),
    _list("education_levels", "Education levels", EducationLevel,
          ExtraField("level_rank", "Level rank", "int", required=True)),
    _list("experience_bands", "Experience bands", ExperienceBand,
          ExtraField("min_months", "Minimum months", "int", required=True),
          ExtraField("max_months", "Maximum months", "int")),
    _list("job_types", "Job types", JobType),
    _list("work_modes", "Work modes", WorkMode),
    _list("pay_types", "Pay types", PayType),
    _list("lookup_values", "Other lookup values", LookupValue,
          ExtraField("list_code", "List code", "text", required=True, immutable=True), public=False),
)}


def get_list(key: str) -> ReferenceListDef:
    from js_core.errors import NotFound

    definition = LISTS.get(key)
    if definition is None:
        raise NotFound("Unknown reference list.", code="UNKNOWN_LIST")
    return definition
