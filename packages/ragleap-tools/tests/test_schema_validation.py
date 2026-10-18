"""validate_arguments / drop_null_optionals: the argument checks that run before a handler."""
import pytest

from ragleap_tools._schema import MAX_DEPTH, drop_null_optionals, validate_arguments

SCHEMA = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
    "required": ["name"],
}


def test_valid_arguments_pass():
    assert validate_arguments(SCHEMA, {"name": "x", "count": 3}) is None
    assert validate_arguments(SCHEMA, {"name": "x"}) is None


def test_missing_required_argument_is_named():
    assert validate_arguments(SCHEMA, {"count": 1}) == "missing required argument 'name'"


def test_unknown_argument_is_rejected_when_properties_are_declared():
    assert validate_arguments(SCHEMA, {"name": "x", "zzz": 1}) == "unknown argument 'zzz'"


def test_unknown_argument_allowed_when_additional_properties_true():
    s = dict(SCHEMA, additionalProperties=True)
    assert validate_arguments(s, {"name": "x", "zzz": 1}) is None


def test_unknown_argument_allowed_when_schema_has_no_properties():
    assert validate_arguments({"type": "object"}, {"anything": 1}) is None
    assert validate_arguments({"type": "object", "properties": {}}, {"anything": 1}) is None


def test_additional_properties_false_rejects_extras_even_without_properties():
    assert validate_arguments({"type": "object", "additionalProperties": False}, {"a": 1}) == "unknown argument 'a'"


def test_additional_properties_schema_validates_extras():
    s = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": {"type": "integer"}}
    assert validate_arguments(s, {"a": "x", "b": 2}) is None
    assert "argument 'b' must be of type integer" == validate_arguments(s, {"a": "x", "b": "no"})


@pytest.mark.parametrize(
    "typ,bad",
    [
        ("string", 1), ("integer", "1"), ("integer", 1.5), ("number", "1"), ("boolean", 1),
        ("array", {}), ("object", []), ("null", 0),
    ],
)
def test_wrong_types_are_rejected(typ, bad):
    err = validate_arguments({"properties": {"v": {"type": typ}}}, {"v": bad})
    assert err == "argument 'v' must be of type %s" % typ


def test_bool_is_not_an_integer_or_number():
    s = {"properties": {"i": {"type": "integer"}, "n": {"type": "number"}}}
    assert validate_arguments(s, {"i": True}) is not None
    assert validate_arguments(s, {"n": False}) is not None


def test_number_accepts_int_and_float():
    s = {"properties": {"n": {"type": "number"}}}
    assert validate_arguments(s, {"n": 3}) is None
    assert validate_arguments(s, {"n": 3.5}) is None


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_numbers_are_rejected(bad):
    assert validate_arguments({"properties": {"n": {"type": "number"}}}, {"n": bad}) == "argument 'n' must be a finite number"


def test_type_list_accepts_any_listed_type():
    s = {"properties": {"v": {"type": ["string", "null"]}}}
    assert validate_arguments(s, {"v": None}) is None
    assert validate_arguments(s, {"v": "x"}) is None
    assert validate_arguments(s, {"v": 1}) is not None


def test_unknown_schema_type_fails_closed():
    assert validate_arguments({"properties": {"v": {"type": "strng"}}}, {"v": "x"}) is not None


def test_enum_accepts_listed_and_rejects_others():
    s = {"properties": {"m": {"type": "string", "enum": ["a", "b"]}}}
    assert validate_arguments(s, {"m": "a"}) is None
    assert validate_arguments(s, {"m": "c"}) == "argument 'm' must be one of the allowed values"


def test_enum_does_not_confuse_true_with_one():
    s = {"properties": {"m": {"enum": [1, 2]}}}
    assert validate_arguments(s, {"m": True}) is not None
    assert validate_arguments(s, {"m": 1}) is None
    s2 = {"properties": {"m": {"enum": [True]}}}
    assert validate_arguments(s2, {"m": 1}) is not None


def test_string_length_limits():
    s = {"properties": {"v": {"type": "string", "minLength": 2, "maxLength": 3}}}
    assert validate_arguments(s, {"v": "a"}) == "argument 'v' is shorter than 2 characters"
    assert validate_arguments(s, {"v": "abcd"}) == "argument 'v' is longer than 3 characters"
    assert validate_arguments(s, {"v": "abc"}) is None
    assert validate_arguments(s, {"v": "ab"}) is None


def test_numeric_limits():
    s = {"properties": {"v": {"type": "integer", "minimum": 1, "maximum": 5}}}
    assert validate_arguments(s, {"v": 0}) == "argument 'v' is below the minimum 1"
    assert validate_arguments(s, {"v": 6}) == "argument 'v' is above the maximum 5"
    assert validate_arguments(s, {"v": 5}) is None
    assert validate_arguments(s, {"v": 1}) is None


def test_array_limits_and_items_are_checked_with_an_index():
    s = {"properties": {"v": {"type": "array", "items": {"type": "integer"}, "minItems": 1, "maxItems": 2}}}
    assert validate_arguments(s, {"v": []}) == "argument 'v' has fewer than 1 items"
    assert validate_arguments(s, {"v": [1, 2, 3]}) == "argument 'v' has more than 2 items"
    assert validate_arguments(s, {"v": [1, "x"]}) == "argument 'v'[1] must be of type integer"
    assert validate_arguments(s, {"v": [1, 2]}) is None
    assert validate_arguments(s, {"v": [1]}) is None


def test_nested_object_required_and_unknown_keys():
    s = {"properties": {"o": {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"],
                              "additionalProperties": False}}}
    assert validate_arguments(s, {"o": {"a": "x"}}) is None
    assert validate_arguments(s, {"o": {}}) == "argument 'o' is missing 'a'"
    assert validate_arguments(s, {"o": {"a": 1}}) == "argument 'o'.a must be of type string"
    assert validate_arguments(s, {"o": {"a": "x", "b": 1}}) == "argument 'o' has an unknown key"


def test_nested_extra_keys_are_allowed_by_default():
    s = {"properties": {"o": {"type": "object", "properties": {"a": {"type": "string"}}}}}
    assert validate_arguments(s, {"o": {"a": "x", "b": 1}}) is None


def _nested_schema(depth):
    schema = {"type": "object", "properties": {}}
    for _ in range(depth):
        schema = {"type": "object", "properties": {"v": schema}}
    return schema


def _nested_value(depth):
    value = {}
    for _ in range(depth):
        value = {"v": value}
    return value


def test_deep_nesting_returns_an_error_not_a_recursion_error():
    err = validate_arguments(_nested_schema(MAX_DEPTH + 10), _nested_value(MAX_DEPTH + 10))
    assert err is not None and "nested too deeply" in err


def test_nesting_within_the_limit_is_accepted():
    assert validate_arguments(_nested_schema(5), _nested_value(5)) is None


def test_arguments_must_be_a_dict():
    for bad in ([1], "x", 5, None):
        assert validate_arguments(SCHEMA, bad) == "arguments must be a JSON object"


def test_non_string_argument_names_are_rejected():
    assert validate_arguments({"type": "object"}, {1: "x"}) == "argument names must be strings"


def test_a_non_dict_schema_accepts_any_object():
    assert validate_arguments(None, {"a": 1}) is None


def test_error_text_clips_long_and_control_characters():
    long_key = "k" * 5000
    err = validate_arguments(SCHEMA, {"name": "x", long_key: 1})
    assert len(err) < 100 and err.endswith("...'")
    err2 = validate_arguments(SCHEMA, {"name": "x", "a\nb\x00c": 1})
    assert "\n" not in err2 and "\x00" not in err2


def test_keywords_outside_the_subset_are_ignored():
    s = {"properties": {"v": {"type": "string", "pattern": "^a$", "format": "email"}}}
    assert validate_arguments(s, {"v": "zzz"}) is None


def test_drop_null_optionals_drops_only_optional_non_null_properties():
    s = {"properties": {"a": {"type": "string"}, "b": {"type": "string"}, "c": {"type": ["string", "null"]},
                        "d": {}}, "required": ["a"]}
    out = drop_null_optionals(s, {"a": None, "b": None, "c": None, "d": None, "e": None})
    assert out == {"a": None, "c": None, "d": None, "e": None}


def test_drop_null_optionals_without_properties_is_a_no_op():
    args = {"a": None}
    assert drop_null_optionals({"type": "object"}, args) is args
    assert drop_null_optionals(None, args) is args


def test_drop_null_optionals_does_not_mutate_the_input():
    s = {"properties": {"b": {"type": "string"}}}
    args = {"b": None}
    drop_null_optionals(s, args)
    assert args == {"b": None}
