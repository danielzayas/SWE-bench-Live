from swebench.harness import run_validation


def test_is_validated_instance_requires_fail_to_pass():
    assert not run_validation.is_validated_instance(["tests/foo::bar"], [])
    assert run_validation.is_validated_instance([], ["tests/foo::bar"])
    assert run_validation.is_validated_instance(["tests/foo::baz"], ["tests/foo::bar"])
