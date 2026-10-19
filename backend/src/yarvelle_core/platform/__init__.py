# Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
# Copyright 2026 Spectrayan (https://spectrayan.com)
#
# Licensed under the PolyForm Noncommercial License 1.0.0 and the
# Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
# Personal and household local use only. Commercial use, hosted service
# offering, rebranding, white-labeling, and redistribution of modified
# forks are prohibited without a written commercial license from Spectrayan.
#
# Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

"""Yarvelle Core platform foundation services: reminders, scheduled routines, and email drafts."""

from yarvelle_core.platform.email_drafts import (
    NO_AUTO_SEND_NOTICE,
    build_mailto_uri,
    create_email_draft,
    delete_email_draft,
    execute_create_email_draft,
    export_draft_as_eml,
    get_email_draft,
    list_email_drafts,
    serialize_email_draft,
)
from yarvelle_core.platform.reminders import (
    SNOOZE_DELTAS,
    WEEKDAY_MAP,
    advance_rrule_occurrence,
    apply_reminder_snooze,
    coalesce_overdue_reminders,
    generate_ics_calendar,
    handle_reminder_job,
)
from yarvelle_core.platform.routines import (
    create_standing_routine,
    execute_standing_routine,
    set_connection_autonomy,
    update_standing_routine_status,
)

__all__ = [
    "NO_AUTO_SEND_NOTICE",
    "SNOOZE_DELTAS",
    "WEEKDAY_MAP",
    "advance_rrule_occurrence",
    "apply_reminder_snooze",
    "build_mailto_uri",
    "coalesce_overdue_reminders",
    "create_email_draft",
    "create_standing_routine",
    "delete_email_draft",
    "execute_create_email_draft",
    "execute_standing_routine",
    "export_draft_as_eml",
    "generate_ics_calendar",
    "get_email_draft",
    "handle_reminder_job",
    "list_email_drafts",
    "serialize_email_draft",
    "set_connection_autonomy",
    "update_standing_routine_status",
]
