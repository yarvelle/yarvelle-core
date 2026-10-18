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

"""Dual-write compatibility adapter synchronizing ProfileAccess and ScopeGrant (Step C2b)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
import uuid

from sqlalchemy import delete, event, inspect, select
from sqlalchemy.orm import Mapper, Session

if TYPE_CHECKING:
    from yarvelle_core.db.models import ProfileAccess, ProfileConsent, ScopeGrant


class DualWriteAdapter:
    """Manages bidirectional consistency between legacy access controls and scope_grants."""

    _registered: bool = False

    @classmethod
    def sync_profile_access_to_scope_grants(cls, session: Session, access: ProfileAccess) -> None:
        """Translates ProfileAccess row into corresponding ScopeGrant records."""
        if not access.profile_id or not access.user_id:
            return

        from yarvelle_core.db.models import ScopeGrant

        # Clear existing health scope grants for this profile+user pair
        session.execute(
            delete(ScopeGrant).where(
                ScopeGrant.profile_id == access.profile_id,
                ScopeGrant.user_id == access.user_id,
                ScopeGrant.scope.like("health%"),
            )
        )

        grant_time = access.granted_at
        if access.access_level == "manage":
            targets = [("health.*", "write"), ("health.*", "approve")]
        elif access.access_level == "view_records" or access.access_level == "view_clinical":
            targets = [("health.records", "read"), ("health.paperwork", "read")]
        elif access.access_level == "view_paperwork":
            targets = [("health.paperwork", "read")]
        else:
            targets = [("health.*", "read")]

        for sc, lvl in targets:
            session.add(
                ScopeGrant(
                    id=str(uuid.uuid4()),
                    profile_id=access.profile_id,
                    user_id=access.user_id,
                    scope=sc,
                    access_level=lvl,
                    granted_at=grant_time,
                    granted_by=access.granted_by,
                )
            )

    @classmethod
    def remove_profile_access_grants(cls, session: Session, access: ProfileAccess) -> None:
        """Removes scope grants when ProfileAccess is deleted."""
        if not access.profile_id or not access.user_id:
            return
        from yarvelle_core.db.models import ScopeGrant

        session.execute(
            delete(ScopeGrant).where(
                ScopeGrant.profile_id == access.profile_id,
                ScopeGrant.user_id == access.user_id,
                ScopeGrant.scope.like("health%"),
            )
        )

    @classmethod
    def sync_profile_consent_to_scope_grants(cls, session: Session, consent: ProfileConsent) -> None:
        """Translates ProfileConsent allow_clinical toggle into ScopeGrant records."""
        if not consent.profile_id:
            return

        from yarvelle_core.db.models import ScopeGrant

        if consent.allow_clinical:
            stmt = select(ScopeGrant).where(
                ScopeGrant.profile_id == consent.profile_id,
                ScopeGrant.user_id.is_(None),
                ScopeGrant.scope == "health.records",
            )
            existing = session.execute(stmt).scalar_one_or_none()
            if not existing:
                session.add(
                    ScopeGrant(
                        id=str(uuid.uuid4()),
                        profile_id=consent.profile_id,
                        user_id=None,
                        scope="health.records",
                        access_level="read",
                        granted_at=consent.updated_at or consent.created_at,
                    )
                )
        else:
            session.execute(
                delete(ScopeGrant).where(
                    ScopeGrant.profile_id == consent.profile_id,
                    ScopeGrant.user_id.is_(None),
                    ScopeGrant.scope == "health.records",
                )
            )

    @classmethod
    def register_listeners(cls) -> None:
        """Attaches SQLAlchemy event listeners for dual-write synchronization."""
        if cls._registered:
            return

        from yarvelle_core.db.models import ProfileAccess, ProfileConsent

        @event.listens_for(ProfileAccess, "after_insert")
        def _on_profile_access_insert(mapper: Mapper[ProfileAccess], connection: Any, target: ProfileAccess) -> None:
            session = Session.object_session(target)
            if session is not None and not session.info.get("skip_dual_write", False):
                cls.sync_profile_access_to_scope_grants(session, target)

        @event.listens_for(ProfileAccess, "after_update")
        def _on_profile_access_update(mapper: Mapper[ProfileAccess], connection: Any, target: ProfileAccess) -> None:
            session = Session.object_session(target)
            if session is not None and not session.info.get("skip_dual_write", False):
                cls.sync_profile_access_to_scope_grants(session, target)

        @event.listens_for(ProfileAccess, "after_delete")
        def _on_profile_access_delete(mapper: Mapper[ProfileAccess], connection: Any, target: ProfileAccess) -> None:
            session = Session.object_session(target)
            if session is not None and not session.info.get("skip_dual_write", False):
                cls.remove_profile_access_grants(session, target)

        @event.listens_for(ProfileConsent, "after_insert")
        def _on_profile_consent_insert(mapper: Mapper[ProfileConsent], connection: Any, target: ProfileConsent) -> None:
            session = Session.object_session(target)
            if session is not None and not session.info.get("skip_dual_write", False):
                cls.sync_profile_consent_to_scope_grants(session, target)

        @event.listens_for(ProfileConsent, "after_update")
        def _on_profile_consent_update(mapper: Mapper[ProfileConsent], connection: Any, target: ProfileConsent) -> None:
            session = Session.object_session(target)
            if session is not None and not session.info.get("skip_dual_write", False):
                cls.sync_profile_consent_to_scope_grants(session, target)

        cls._registered = True


__all__ = ["DualWriteAdapter"]
