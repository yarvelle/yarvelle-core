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

import { describe, it, expect, vi } from 'vitest';
import * as React from 'react';
import { renderToString } from 'react-dom/server';
import {
  DeliberationRoundtable,
  RoundtableCard,
  type DeliberationRoundtableProps,
  type DeliberationSpecialistProposal,
  type DeliberationPeerCritique,
  type DeliberationMinorityReportItem,
  type StagedActionItem,
} from '../src/index.js';

describe('DeliberationRoundtable & RoundtableCard Component Suite', () => {
  const sampleProposals: DeliberationSpecialistProposal[] = [
    {
      agent_id: 'agent-alpha',
      round_num: 1,
      summary: 'Initial proposal for resource allocation scenario.',
      recommendations: ['Allocate compute unit batch A', 'Set sync interval to 5s'],
      resource_claims: { compute: 4, memory: 256 },
      resource_claim_units: { compute: 'cores', memory: 'MB' },
      confidence: 0.92,
    },
    {
      agent_id: 'agent-beta',
      round_num: 1,
      summary: 'Secondary proposal requesting storage bandwidth.',
      recommendations: ['Open read pipeline on shared storage'],
      resource_claims: { storage: 50 },
      resource_claim_units: { storage: 'GB' },
      tainted: true,
      confidence: 0.85,
    },
    {
      agent_id: 'agent-alpha',
      round_num: 2,
      summary: 'Revised proposal accommodating peer memory critique.',
      recommendations: ['Allocate compute unit batch A', 'Reduce memory buffer to 128 MB'],
      resource_claims: { compute: 4, memory: 128 },
      resource_claim_units: { compute: 'cores', memory: 'MB' },
      confidence: 0.95,
    },
  ];

  const sampleCritiques: DeliberationPeerCritique[] = [
    {
      reviewer_agent_id: 'agent-gamma',
      target_agent_id: 'agent-alpha',
      round_num: 1,
      stance: 'amend',
      issue_type: 'resource_overbudget',
      critique: 'Memory allocation exceeds shared quota.',
      proposed_resolution: 'Reduce memory buffer to 128 MB.',
    },
    {
      reviewer_agent_id: 'agent-beta',
      target_agent_id: 'agent-alpha',
      round_num: 1,
      stance: 'endorse',
      issue_type: 'synergy',
      critique: 'Compute core distribution aligns with batch execution goals.',
      proposed_resolution: 'Retain 4 compute cores allocation.',
    },
    {
      reviewer_agent_id: 'agent-gamma',
      target_agent_id: 'agent-beta',
      round_num: 2,
      stance: 'complement',
      issue_type: 'dependency_order',
      critique: 'Pipeline synchronization requires sequential initialization.',
      proposed_resolution: 'Initialize storage pipeline before batch launch.',
    },
    {
      reviewer_agent_id: 'agent-delta',
      target_agent_id: 'agent-beta',
      round_num: 2,
      stance: 'conflict',
      issue_type: 'risk_exposure',
      critique: 'Unbounded storage throughput risks starvation for other processes.',
      proposed_resolution: 'Cap throughput at 25 MB/s.',
    },
  ];

  const sampleMinorityReport: DeliberationMinorityReportItem[] = [
    {
      issue_type: 'risk_exposure',
      target_agent_id: 'agent-beta',
      reviewer_agent_id: 'agent-delta',
      target_position: 'High throughput pipeline essential for real-time indexing.',
      target_recommendations: ['Maintain uncapped burst mode'],
      reviewer_critique: 'Unbounded throughput risks system-wide I/O starvation.',
      reviewer_proposed_resolution: 'Cap throughput at 25 MB/s.',
    },
  ];

  const sampleOpenAmendments: DeliberationPeerCritique[] = [
    {
      reviewer_agent_id: 'agent-gamma',
      target_agent_id: 'agent-beta',
      round_num: 2,
      stance: 'amend',
      issue_type: 'dependency_order',
      critique: 'Initialization sequence advisory recommendation remains pending.',
      proposed_resolution: 'Review sequence in pipeline staging.',
    },
  ];

  const sampleStagedActions: StagedActionItem[] = [
    {
      id: 'act-1',
      agent_id: 'agent-alpha',
      tool_name: 'execute_batch',
      tool_args: { batch_size: 100 },
      rationale: 'Execute scheduled batch processing run.',
      risk_tier: 'write_local',
      status: 'pending',
    },
    {
      id: 'act-2',
      agent_id: 'agent-beta',
      tool_name: 'send_webhook',
      tool_args: { target_url: 'https://example.com/hook' },
      rationale: 'Publish completion event to external webhook.',
      risk_tier: 'write_external',
      status: 'pending',
    },
    {
      id: 'act-3',
      agent_id: 'agent-gamma',
      tool_name: 'purge_index',
      tool_args: { namespace: 'obsolete' },
      rationale: 'Permanently remove obsolete partition index.',
      risk_tier: 'irreversible',
      status: 'pending',
    },
    {
      id: 'act-4',
      agent_id: 'agent-delta',
      tool_name: 'inspect_metrics',
      tool_args: { range: '1h' },
      rationale: 'Query performance telemetry metrics.',
      risk_tier: 'read',
      status: 'pending',
    },
  ];

  it('renders root container with stable classes, data-slot, and accessibility attributes', () => {
    const html = renderToString(
      <DeliberationRoundtable
        panel_id="panel-core-1"
        title="Architecture Review Roundtable"
        agents={['agent-alpha', 'agent-beta']}
      />
    );

    expect(html).toContain('yc-DeliberationRoundtable-root');
    expect(html).toContain('yc-RoundtableCard-root');
    expect(html).toContain('data-slot="deliberation-roundtable"');
    expect(html).toContain('role="region"');
    expect(html).toContain('aria-label="Multi-Agent Deliberation Roundtable"');
    expect(html).toContain('Architecture Review Roundtable');
    expect(html).toContain('panel-core-1');
  });

  it('renders RoundtableCard alias identically to DeliberationRoundtable', () => {
    const html = renderToString(
      <RoundtableCard
        panel_id="panel-alias-1"
        title="Alias Check"
        agents={['agent-1']}
      />
    );

    expect(html).toContain('yc-DeliberationRoundtable-root');
    expect(html).toContain('yc-RoundtableCard-root');
    expect(html).toContain('data-slot="deliberation-roundtable"');
    expect(html).toContain('panel-alias-1');
  });

  it('renders panel header with status badge and specialist agent pills', () => {
    const html = renderToString(
      <DeliberationRoundtable
        title="System Panel"
        agents={['agent-alpha', 'agent-beta', 'agent-gamma']}
        converged={true}
        rounds_used={2}
      />
    );

    expect(html).toContain('data-slot="panel-header"');
    expect(html).toContain('data-slot="agent-pills"');
    expect(html).toContain('data-slot="agent-pill"');
    expect(html).toContain('agent-alpha');
    expect(html).toContain('agent-beta');
    expect(html).toContain('agent-gamma');
    expect(html).toContain('Converged');
    expect(html).toContain('Rounds: 2');
  });

  it('renders constraint meters including within limit, overbudget, and skipped limits', () => {
    const html = renderToString(
      <DeliberationRoundtable
        agents={['agent-alpha']}
        shared_constraints={[
          {
            id: 'compute_budget',
            description: 'Core capacity limit',
            unit: 'cores',
            limit_value: 8,
            total_claimed: 4,
          },
          {
            id: 'memory_budget',
            description: 'RAM allocation limit',
            unit: 'MB',
            limit_value: 200,
            total_claimed: 256,
          },
          {
            id: 'network_bandwidth',
            description: 'Egress rate cap',
            unit: 'MB/s',
            limit_value: null, // Unknown limit -> skipped
          },
        ]}
      />
    );

    expect(html).toContain('data-slot="constraint-meters"');
    expect(html).toContain('data-slot="constraint-item"');
    expect(html).toContain('compute_budget');
    expect(html).toContain('Within limit');
    expect(html).toContain('memory_budget');
    expect(html).toContain('Overbudget (+56.0)');
    expect(html).toContain('data-slot="constraint-skipped"');
    expect(html).toContain('Limit Unknown (Skipped)');
  });

  it('renders skipped constraints identified via skipped_constraints list', () => {
    const html = renderToString(
      <DeliberationRoundtable
        agents={['agent-alpha']}
        skipped_constraints={['disk_io']}
        shared_constraints={[
          {
            id: 'disk_io',
            unit: 'IOPS',
            limit_value: 1000,
            total_claimed: 500,
          },
        ]}
      />
    );

    expect(html).toContain('data-slot="constraint-skipped"');
    expect(html).toContain('Limit Unknown (Skipped)');
  });

  it('renders specialist proposal cards with revision and taint badges', () => {
    const html = renderToString(
      <DeliberationRoundtable
        agents={['agent-alpha', 'agent-beta']}
        proposals={sampleProposals}
      />
    );

    expect(html).toContain('data-slot="proposals-section"');
    expect(html).toContain('data-slot="proposal-card"');
    expect(html).toContain('Initial proposal for resource allocation scenario.');
    expect(html).toContain('data-slot="recommendations"');
    expect(html).toContain('Allocate compute unit batch A');
    expect(html).toContain('data-slot="resource-claims"');
    expect(html).toContain('compute: 4 cores');

    // Round 2 proposal has revision badge
    expect(html).toContain('data-slot="revision-badge"');
    expect(html).toContain('Revised after peer review');

    // Agent Beta proposal is tainted -> taint badge
    expect(html).toContain('data-slot="taint-badge"');
    expect(html).toContain('⚠️ Untrusted Source');

    // Confidence indicator
    expect(html).toContain('conf: 92%');
  });

  it('renders Disagree-or-Commit peer critiques with stance badges and connectors', () => {
    const html = renderToString(
      <DeliberationRoundtable
        agents={['agent-alpha', 'agent-beta', 'agent-gamma', 'agent-delta']}
        critiques={sampleCritiques}
      />
    );

    expect(html).toContain('data-slot="critiques-section"');
    expect(html).toContain('data-slot="critique-item"');
    expect(html).toContain('agent-gamma → agent-alpha');
    expect(html).toContain('data-slot="stance-badge"');
    expect(html).toContain('AMEND');
    expect(html).toContain('ENDORSE');
    expect(html).toContain('COMPLEMENT');
    expect(html).toContain('CONFLICT');
    expect(html).toContain('resource_overbudget');
    expect(html).toContain('Memory allocation exceeds shared quota.');
    expect(html).toContain('Proposed:');
    expect(html).toContain('Reduce memory buffer to 128 MB.');
  });

  it('renders minority report with Option A vs. Option B and open amendment notes', () => {
    const html = renderToString(
      <DeliberationRoundtable
        agents={['agent-beta', 'agent-delta']}
        minority_reports={sampleMinorityReport}
        open_amendments={sampleOpenAmendments}
      />
    );

    // Minority report
    expect(html).toContain('data-slot="minority-report"');
    expect(html).toContain('Minority Report: Unresolved Conflicts');
    expect(html).toContain('data-slot="minority-option"');
    expect(html).toContain('data-option="A"');
    expect(html).toContain('Option A (agent-beta Position)');
    expect(html).toContain('High throughput pipeline essential for real-time indexing.');
    expect(html).toContain('data-option="B"');
    expect(html).toContain('Option B (agent-delta Position)');
    expect(html).toContain('Unbounded throughput risks system-wide I/O starvation.');
    expect(html).toContain('Stakeholder Decision Required');

    // Open amendments
    expect(html).toContain('data-slot="open-amendments"');
    expect(html).toContain('Open Amendments');
    expect(html).toContain('Initialization sequence advisory recommendation remains pending.');
  });

  it('renders staged actions integrated with ApprovalCard and maps risk tiers deterministically', () => {
    const html = renderToString(
      <DeliberationRoundtable
        agents={['agent-alpha', 'agent-beta', 'agent-gamma', 'agent-delta']}
        staged_actions={sampleStagedActions}
      />
    );

    expect(html).toContain('data-slot="staged-actions"');
    expect(html).toContain('data-slot="approval-card"');
    expect(html).toContain('Staged Actions for Human Approval');

    // Risk tier mapping
    // write_local -> warn
    expect(html).toContain('data-risk-level="warn"');
    expect(html).toContain('agent-alpha: execute_batch');

    // write_external -> warn
    expect(html).toContain('agent-beta: send_webhook');

    // irreversible -> danger
    expect(html).toContain('data-risk-level="danger"');
    expect(html).toContain('agent-gamma: purge_index');

    // read -> info
    expect(html).toContain('data-risk-level="info"');
    expect(html).toContain('agent-delta: inspect_metrics');
  });

  it('handles proposals and critiques provided as record maps by round number', () => {
    const recordProposals = {
      1: {
        'agent-1': {
          agent_id: 'agent-1',
          round_num: 1,
          summary: 'Round 1 plan',
        },
      },
    };
    const recordCritiques = {
      1: [
        {
          reviewer_agent_id: 'agent-2',
          target_agent_id: 'agent-1',
          round_num: 1,
          stance: 'endorse' as const,
          issue_type: 'synergy',
          critique: 'Agreed with plan',
          proposed_resolution: 'Proceed',
        },
      ],
    };

    const html = renderToString(
      <DeliberationRoundtable
        agents={['agent-1', 'agent-2']}
        proposals={recordProposals}
        critiques={recordCritiques}
      />
    );

    expect(html).toContain('Round 1 plan');
    expect(html).toContain('agent-2 → agent-1');
    expect(html).toContain('ENDORSE');
  });
});
