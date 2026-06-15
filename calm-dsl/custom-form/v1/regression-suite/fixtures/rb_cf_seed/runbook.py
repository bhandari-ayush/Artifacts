"""Synthetic runbook with a CustomForm attached at the RunbookService level."""

from calm.dsl.runbooks import CustomForm, runbook, RunbookTask


@runbook
def DslRunbook(endpoints=[]):
    """A trivial runbook so we can attach a CustomForm to it."""

    RunbookTask.SetVariable.escript(
        name="set_var", script="print('rb_cf')", variables=["VAR_OUT"]
    )


# Parent RunbookService compile auto-loads specs/runbook_rb_cf_form.yaml.
# Set on ``DslRunbook.runbook`` (the underlying RunbookServiceType); attrs
# on the bare ``DslRunbook`` descriptor are dropped on the floor.
DslRunbook.runbook.custom_form = CustomForm(name="rb_cf_form")
DslRunbook.runbook.use_custom_form = False
