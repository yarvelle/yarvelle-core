// Yarvelle Core — Domain-Neutral AI Agent Runtime & Execution Engine
// Copyright 2026 Spectrayan (https://spectrayan.com)
//
// Licensed under the PolyForm Noncommercial License 1.0.0 and the
// Yarvelle Core Additional Terms (see LICENSE and ADDITIONAL-TERMS.md).
// Personal and household local use only. Commercial use, hosted service
// offering, rebranding, white-labeling, and redistribution of modified
// forks are prohibited without a written commercial license from Spectrayan.
//
// Required Notice: Copyright 2026 Spectrayan (https://spectrayan.com)

import * as React from 'react';
import { cn } from '../lib/cn.js';
import { Badge } from '../primitives/Badge.js';
import { ApprovalCard } from './ApprovalCard.js';
import type {
  RiskLevel,
  DeliberationCritiqueStance,
  StagedActionRiskTier,
  DeliberationSpecialistProposal,
  DeliberationPeerCritique,
  DeliberationRoundtableProps,
} from './types.js';

const stanceBadgeVariant: Record<DeliberationCritiqueStance, 'success' | 'info' | 'warn' | 'danger'> = {
  endorse: 'success',
  complement: 'info',
  amend: 'warn',
  conflict: 'danger',
};

function mapRiskTierToLevel(tier?: StagedActionRiskTier | string): RiskLevel {
  switch (tier) {
    case 'irreversible':
      return 'danger';
    case 'write_external':
    case 'write_local':
      return 'warn';
    case 'read':
      return 'info';
    default:
      return 'danger'; // Fail-closed security invariant
  }
}

export function DeliberationRoundtable({
  panel_id,
  title,
  agents = [],
  shared_constraints,
  skipped_constraints,
  proposals,
  critiques,
  staged_actions,
  rounds_used,
  converged,
  termination_reason,
  minority_reports,
  open_amendments,
  className,
  onApproveStagedAction,
}: DeliberationRoundtableProps) {
  // Normalize proposals into flat array
  const proposalList = React.useMemo<DeliberationSpecialistProposal[]>(() => {
    if (!proposals) return [];
    if (Array.isArray(proposals)) return proposals;
    const flat: DeliberationSpecialistProposal[] = [];
    for (const roundKey of Object.keys(proposals)) {
      const roundProposals = proposals[Number(roundKey)];
      if (roundProposals) {
        for (const agentKey of Object.keys(roundProposals)) {
          flat.push(roundProposals[agentKey]);
        }
      }
    }
    return flat;
  }, [proposals]);

  // Normalize critiques into flat array
  const critiqueList = React.useMemo<DeliberationPeerCritique[]>(() => {
    if (!critiques) return [];
    if (Array.isArray(critiques)) return critiques;
    const flat: DeliberationPeerCritique[] = [];
    for (const roundKey of Object.keys(critiques)) {
      const roundCritiques = critiques[Number(roundKey)];
      if (Array.isArray(roundCritiques)) {
        flat.push(...roundCritiques);
      }
    }
    return flat;
  }, [critiques]);

  // Discover all unique rounds
  const availableRounds = React.useMemo(() => {
    const roundSet = new Set<number>();
    proposalList.forEach((p) => roundSet.add(p.round_num));
    critiqueList.forEach((c) => roundSet.add(c.round_num));
    return Array.from(roundSet).sort((a, b) => a - b);
  }, [proposalList, critiqueList]);

  const [selectedRound, setSelectedRound] = React.useState<number | 'all'>('all');

  const filteredProposals = React.useMemo(() => {
    if (selectedRound === 'all') return proposalList;
    return proposalList.filter((p) => p.round_num === selectedRound);
  }, [proposalList, selectedRound]);

  const filteredCritiques = React.useMemo(() => {
    if (selectedRound === 'all') return critiqueList;
    return critiqueList.filter((c) => c.round_num === selectedRound);
  }, [critiqueList, selectedRound]);

  // Determine status badge
  const renderStatusBadge = () => {
    if (converged) {
      return <Badge variant="success">Converged</Badge>;
    }
    if (termination_reason === 'max_rounds') {
      return <Badge variant="warn">Max Rounds Reached</Badge>;
    }
    if (termination_reason === 'budget') {
      return <Badge variant="danger">Budget Exceeded</Badge>;
    }
    if (termination_reason === 'cancelled') {
      return <Badge variant="danger">Cancelled</Badge>;
    }
    if (termination_reason) {
      return <Badge variant="neutral">{termination_reason}</Badge>;
    }
    return null;
  };

  return (
    <div
      role="region"
      aria-label="Multi-Agent Deliberation Roundtable"
      data-slot="deliberation-roundtable"
      className={cn(
        'yc-DeliberationRoundtable-root yc-RoundtableCard-root my-3 rounded-lg border border-border bg-surface p-4 text-xs shadow-1 space-y-4',
        className
      )}
    >
      {/* 1. Panel Header & Constraint Meters */}
      <div data-slot="panel-header" className="yc-DeliberationRoundtable-header flex flex-col gap-2 pb-3 border-b border-border">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <h3 data-slot="title" className="yc-DeliberationRoundtable-title text-sm font-semibold text-fg">
              {title || 'Multi-Agent Deliberation'}
            </h3>
            {panel_id && <Badge variant="outline">{panel_id}</Badge>}
          </div>
          <div className="flex items-center gap-1.5">
            {renderStatusBadge()}
            {rounds_used != null && <Badge variant="neutral">{`Rounds: ${rounds_used}`}</Badge>}
          </div>
        </div>

        {/* Participating Agent Pills */}
        {agents.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5" data-slot="agent-pills">
            <span className="text-fg-muted font-medium">Specialists:</span>
            {agents.map((agent) => (
              <Badge key={agent} variant="neutral" data-slot="agent-pill">
                {agent}
              </Badge>
            ))}
          </div>
        )}

        {/* Shared Constraint Meters */}
        {shared_constraints && shared_constraints.length > 0 && (
          <div className="space-y-1.5 pt-1" data-slot="constraint-meters">
            <span className="text-fg-muted font-medium text-[11px]">Shared Constraints:</span>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {shared_constraints.map((c) => {
                const isSkipped =
                  c.limit_value == null ||
                  c.skipped === true ||
                  (skipped_constraints && skipped_constraints.includes(c.id));
                const claimed = c.total_claimed ?? 0;
                const isOver = !isSkipped && c.limit_value != null && claimed > c.limit_value;
                const overAmount = isOver ? claimed - c.limit_value! : 0;

                return (
                  <div
                    key={c.id}
                    data-slot="constraint-item"
                    className="yc-DeliberationRoundtable-constraintItem flex items-center justify-between p-2 rounded bg-surface-2 border border-border"
                  >
                    <div className="flex flex-col">
                      <span className="font-semibold text-fg">{c.id}</span>
                      {c.description && <span className="text-fg-muted text-[11px]">{c.description}</span>}
                    </div>
                    {isSkipped ? (
                      <Badge variant="neutral" data-slot="constraint-skipped">
                        Limit Unknown (Skipped)
                      </Badge>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className="text-fg-muted font-mono">
                          {claimed} / {c.limit_value} {c.unit}
                        </span>
                        {isOver ? (
                          <Badge variant="danger">{`Overbudget (+${overAmount.toFixed(1)})`}</Badge>
                        ) : (
                          <Badge variant="success">Within limit</Badge>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}
      </div>

      {/* 2. Round-by-Round Specialist Proposals */}
      {filteredProposals.length > 0 && (
        <div data-slot="proposals-section" className="yc-DeliberationRoundtable-proposals space-y-3">
          <div className="flex items-center justify-between gap-2 pb-1" data-slot="proposals-header">
            <h4 className="text-sm font-semibold text-fg">Specialist Proposals</h4>
            {availableRounds.length > 1 && (
              <div className="flex items-center gap-1" data-slot="round-tabs" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={selectedRound === 'all'}
                  className={cn(
                    'px-2 py-0.5 rounded text-[11px] font-medium transition-colors',
                    selectedRound === 'all'
                      ? 'bg-primary text-primary-fg'
                      : 'bg-surface-2 text-fg-muted hover:bg-surface-3'
                  )}
                  onClick={() => setSelectedRound('all')}
                >
                  All Rounds
                </button>
                {availableRounds.map((r) => (
                  <button
                    key={r}
                    type="button"
                    role="tab"
                    aria-selected={selectedRound === r}
                    className={cn(
                      'px-2 py-0.5 rounded text-[11px] font-medium transition-colors',
                      selectedRound === r
                        ? 'bg-primary text-primary-fg'
                        : 'bg-surface-2 text-fg-muted hover:bg-surface-3'
                    )}
                    onClick={() => setSelectedRound(r)}
                  >
                    {`Round ${r}`}
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="space-y-3">
            {filteredProposals.map((p, idx) => (
              <div
                key={`${p.agent_id}-${p.round_num}-${idx}`}
                data-slot="proposal-card"
                className="yc-DeliberationRoundtable-proposalCard rounded border border-border bg-surface-2 p-3 space-y-2"
              >
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-fg text-sm">{p.agent_id}</span>
                    <Badge variant="neutral">{`Round ${p.round_num}`}</Badge>
                    {p.round_num > 1 && (
                      <Badge variant="primary" data-slot="revision-badge">
                        Revised after peer review
                      </Badge>
                    )}
                    {p.tainted === true && (
                      <Badge variant="warn" data-slot="taint-badge">
                        ⚠️ Untrusted Source
                      </Badge>
                    )}
                  </div>
                  {p.confidence != null && (
                    <span className="text-fg-muted font-mono text-[11px]">
                      {`conf: ${(p.confidence * 100).toFixed(0)}%`}
                    </span>
                  )}
                </div>

                <p className="text-fg text-xs leading-relaxed">{p.summary}</p>

                {p.recommendations && p.recommendations.length > 0 && (
                  <div className="space-y-1">
                    <span className="text-fg-muted text-[11px] font-medium">Recommendations:</span>
                    <ul className="space-y-1 ps-4 list-disc text-fg-muted text-xs" data-slot="recommendations">
                      {p.recommendations.map((rec, rIdx) => (
                        <li key={rIdx}>{rec}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {p.resource_claims && Object.keys(p.resource_claims).length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 pt-1" data-slot="resource-claims">
                    <span className="text-fg-muted text-[11px] font-medium">Claims:</span>
                    {Object.entries(p.resource_claims).map(([key, val]) => {
                      const unit = p.resource_claim_units?.[key] || '';
                      return (
                        <Badge key={key} variant="neutral" className="font-mono text-[11px]">
                          {`${key}: ${val}${unit ? ` ${unit}` : ''}`}
                        </Badge>
                      );
                    })}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 3. Disagree-or-Commit Peer Critiques */}
      {filteredCritiques.length > 0 && (
        <div data-slot="critiques-section" className="yc-DeliberationRoundtable-critiques space-y-3">
          <h4 className="text-sm font-semibold text-fg">Peer Critiques & Alignments</h4>
          <div className="space-y-2">
            {filteredCritiques.map((c, idx) => {
              const stanceVariant = stanceBadgeVariant[c.stance] || 'neutral';
              return (
                <div
                  key={`${c.reviewer_agent_id}-${c.target_agent_id}-${c.round_num}-${idx}`}
                  data-slot="critique-item"
                  className="yc-DeliberationRoundtable-critiqueItem flex flex-col gap-1.5 p-2.5 rounded border border-border bg-surface"
                >
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs text-fg font-semibold">
                        {`${c.reviewer_agent_id} → ${c.target_agent_id}`}
                      </span>
                      <Badge variant={stanceVariant} data-slot="stance-badge">
                        {c.stance.toUpperCase()}
                      </Badge>
                      <Badge variant="neutral">{c.issue_type}</Badge>
                    </div>
                    <Badge variant="neutral">{`Round ${c.round_num}`}</Badge>
                  </div>
                  <p className="text-fg-muted text-xs leading-relaxed">{c.critique}</p>
                  {c.proposed_resolution && (
                    <p className="text-fg text-xs font-medium">
                      <span className="text-fg-muted">Proposed: </span>
                      {c.proposed_resolution}
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 4. Minority Report & Open Amendments */}
      {minority_reports && minority_reports.length > 0 && (
        <div data-slot="minority-report" className="space-y-3 rounded-lg border border-danger-border bg-danger-bg/20 p-3">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2">
              <Badge variant="danger">Minority Report</Badge>
              <h4 className="text-sm font-semibold text-fg">Minority Report: Unresolved Conflicts</h4>
            </div>
            <p className="text-xs text-fg-muted">
              The panel did not reach consensus on the following items. Options are presented below for stakeholder review and value judgment.
            </p>
          </div>

          <div className="space-y-3">
            {minority_reports.map((item, idx) => (
              <div key={idx} className="rounded border border-border bg-surface p-3 space-y-2.5">
                <div className="flex items-center gap-2 flex-wrap">
                  <Badge variant="danger">CONFLICT</Badge>
                  <span className="font-mono text-xs font-semibold text-fg">
                    {`${item.reviewer_agent_id} vs. ${item.target_agent_id}`}
                  </span>
                  <Badge variant="neutral">{item.issue_type}</Badge>
                </div>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                  <div data-slot="minority-option" data-option="A" className="p-2.5 rounded bg-surface-2 border border-border space-y-1">
                    <div className="font-semibold text-xs text-fg">{`Option A (${item.target_agent_id} Position)`}</div>
                    <p className="text-xs text-fg-muted leading-relaxed">{item.target_position}</p>
                    {item.target_recommendations && item.target_recommendations.length > 0 && (
                      <ul className="list-disc ps-4 text-[11px] text-fg-muted space-y-0.5 pt-1">
                        {item.target_recommendations.map((rec, ri) => (
                          <li key={ri}>{rec}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                  <div data-slot="minority-option" data-option="B" className="p-2.5 rounded bg-surface-2 border border-border space-y-1">
                    <div className="font-semibold text-xs text-fg">{`Option B (${item.reviewer_agent_id} Position)`}</div>
                    <p className="text-xs text-fg-muted leading-relaxed">{item.reviewer_critique}</p>
                    <p className="text-xs text-fg pt-1">
                      <span className="text-fg-muted font-medium">Proposed: </span>
                      {item.reviewer_proposed_resolution}
                    </p>
                  </div>
                </div>
                <div className="text-xs text-primary font-medium">
                  Stakeholder Decision Required: Value judgment and review required by human stakeholder.
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Open Amendments */}
      {open_amendments && open_amendments.length > 0 && (
        <div data-slot="open-amendments" className="space-y-2 rounded-lg border border-warn-border bg-warn-bg/20 p-3">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2">
              <Badge variant="warn">Open Amendments</Badge>
              <h4 className="text-sm font-semibold text-fg">Advisory Amendment Notes</h4>
            </div>
            <p className="text-xs text-fg-muted">
              The following peer amendment proposals remain open for stakeholder review:
            </p>
          </div>
          <div className="space-y-2">
            {open_amendments.map((amend, idx) => (
              <div key={idx} className="p-2.5 rounded border border-border bg-surface space-y-1">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="font-mono text-xs font-semibold text-fg">
                    {`${amend.reviewer_agent_id} → ${amend.target_agent_id}`}
                  </span>
                  <Badge variant="warn">AMEND</Badge>
                  <Badge variant="neutral">{amend.issue_type}</Badge>
                </div>
                <p className="text-xs text-fg-muted">{amend.critique}</p>
                {amend.proposed_resolution && (
                  <p className="text-xs text-fg">
                    <span className="text-fg-muted font-medium">Proposed: </span>
                    {amend.proposed_resolution}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 5. Staged Actions Integrated with ApprovalCard */}
      {staged_actions && staged_actions.length > 0 && (
        <div data-slot="staged-actions" className="space-y-3 pt-1">
          <div className="space-y-0.5">
            <h4 className="text-sm font-semibold text-fg">Staged Actions for Human Approval</h4>
            <p className="text-xs text-fg-muted">
              All panel-staged actions require human verification before execution.
            </p>
          </div>
          <div className="space-y-2">
            {staged_actions.map((action, idx) => {
              const level = mapRiskTierToLevel(action.risk_tier);
              const actionId = action.id || `staged-${action.agent_id}-${action.tool_name}-${idx}`;
              return (
                <ApprovalCard
                  key={actionId}
                  id={actionId}
                  level={level}
                  label={`${action.agent_id}: ${action.tool_name}`}
                  details={{
                    agent: action.agent_id,
                    tool: action.tool_name,
                    arguments: action.tool_args || {},
                    rationale: action.rationale || '',
                    risk_tier: action.risk_tier,
                  }}
                  status={action.status || 'pending'}
                  onDecide={onApproveStagedAction}
                />
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export { DeliberationRoundtable as RoundtableCard };
