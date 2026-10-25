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

// @ts-ignore
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

import {
  DeliberationRoundtable,
  RoundtableCard,
  type DeliberationRoundtableProps,
  type DeliberationSpecialistProposal,
  type DeliberationPeerCritique,
  type DeliberationConstraint,
  type StagedActionItem,
  type DeliberationMinorityReportItem,
} from '../src/index.js';

describe('DeliberationRoundtable Adversarial Stress Suite', () => {
  describe('1. Empty & Sparse Data Inputs', () => {
    it('renders completely minimal props without crashing', () => {
      const html = renderToString(<DeliberationRoundtable agents={[]} />);
      expect(html).toContain('data-slot="deliberation-roundtable"');
      expect(html).toContain('data-slot="panel-header"');
      expect(html).not.toContain('data-slot="agent-pills"');
      expect(html).not.toContain('data-slot="constraint-meters"');
      expect(html).not.toContain('data-slot="proposals-section"');
      expect(html).not.toContain('data-slot="critiques-section"');
      expect(html).not.toContain('data-slot="minority-report"');
      expect(html).not.toContain('data-slot="open-amendments"');
      expect(html).not.toContain('data-slot="staged-actions"');
    });

    it('renders with undefined/null optional lists', () => {
      const props: DeliberationRoundtableProps = {
        panel_id: undefined,
        title: undefined,
        agents: [],
        shared_constraints: undefined,
        skipped_constraints: undefined,
        proposals: undefined,
        critiques: undefined,
        staged_actions: undefined,
        minority_reports: undefined,
        open_amendments: undefined,
        rounds_used: undefined,
        converged: undefined,
        termination_reason: undefined,
      };

      const html = renderToString(<DeliberationRoundtable {...props} />);
      expect(html).toContain('data-slot="deliberation-roundtable"');
      expect(html).toContain('Multi-Agent Deliberation');
    });

    it('renders with empty arrays for all collections', () => {
      const html = renderToString(
        <DeliberationRoundtable
          agents={[]}
          shared_constraints={[]}
          skipped_constraints={[]}
          proposals={[]}
          critiques={[]}
          staged_actions={[]}
          minority_reports={[]}
          open_amendments={[]}
        />
      );
      expect(html).toContain('data-slot="deliberation-roundtable"');
      expect(html).not.toContain('data-slot="proposals-section"');
      expect(html).not.toContain('data-slot="critiques-section"');
    });

    it('handles record-based proposals and critiques with empty or missing rounds', () => {
      const html = renderToString(
        <DeliberationRoundtable
          agents={['agent-a']}
          proposals={{
            1: {},
            2: {
              'agent-a': {
                agent_id: 'agent-a',
                round_num: 2,
                summary: 'Only in round 2',
              },
            },
          }}
          critiques={{
            1: [],
            3: [
              {
                reviewer_agent_id: 'agent-b',
                target_agent_id: 'agent-a',
                round_num: 3,
                stance: 'endorse',
                issue_type: 'general',
                critique: 'Good alignment',
                proposed_resolution: 'Maintain',
              },
            ],
          }}
        />
      );
      expect(html).toContain('Only in round 2');
      expect(html).toContain('agent-b → agent-a');
      expect(html).toContain('Round 2');
      expect(html).toContain('Round 3');
    });
  });

  describe('2. Extreme Values & Scale', () => {
    it('handles 0 agents gracefully', () => {
      const html = renderToString(<DeliberationRoundtable agents={[]} />);
      expect(html).not.toContain('data-slot="agent-pills"');
    });

    it('handles 100 agents without crashing or dropping slots', () => {
      const agents = Array.from({ length: 100 }, (_, i) => `agent-specialist-${i.toString().padStart(3, '0')}`);
      const html = renderToString(<DeliberationRoundtable agents={agents} />);
      expect(html).toContain('data-slot="agent-pills"');
      expect(html).toContain('agent-specialist-000');
      expect(html).toContain('agent-specialist-099');
    });

    it('handles sparse/gapped round numbers (e.g. 1, 42, 9999)', () => {
      const proposals: DeliberationSpecialistProposal[] = [
        {
          agent_id: 'agent-x',
          round_num: 1,
          summary: 'Round 1 proposal',
        },
        {
          agent_id: 'agent-x',
          round_num: 42,
          summary: 'Round 42 proposal',
        },
        {
          agent_id: 'agent-x',
          round_num: 9999,
          summary: 'Round 9999 proposal',
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['agent-x']} proposals={proposals} />);
      expect(html).toContain('Round 1');
      expect(html).toContain('Round 42');
      expect(html).toContain('Round 9999');
      expect(html).toContain('data-slot="round-tabs"');
    });

    it('handles zero, negative, and extreme resource limits and claims', () => {
      const constraints: DeliberationConstraint[] = [
        {
          id: 'zero_limit',
          unit: 'units',
          limit_value: 0,
          total_claimed: 0,
        },
        {
          id: 'zero_limit_exceeded',
          unit: 'units',
          limit_value: 0,
          total_claimed: 15,
        },
        {
          id: 'negative_limit',
          unit: 'credits',
          limit_value: -100,
          total_claimed: -50,
        },
        {
          id: 'huge_numbers',
          unit: 'bytes',
          limit_value: 1e12,
          total_claimed: 5e11,
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['agent-a']} shared_constraints={constraints} />);
      expect(html).toContain('zero_limit');
      expect(html).toContain('Within limit');
      expect(html).toContain('zero_limit_exceeded');
      expect(html).toContain('Overbudget (+15.0)');
      expect(html).toContain('negative_limit');
      expect(html).toContain('huge_numbers');
    });
  });

  describe('3. Skipped Constraints Handling', () => {
    it('handles skipped constraints with missing limit_value (null & undefined)', () => {
      const constraints: DeliberationConstraint[] = [
        {
          id: 'null_limit',
          unit: 'units',
          limit_value: null,
          total_claimed: 50,
        },
        {
          id: 'undefined_limit',
          unit: 'units',
          limit_value: undefined,
          total_claimed: 20,
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['agent-a']} shared_constraints={constraints} />);
      expect(html).toContain('null_limit');
      expect(html).toContain('undefined_limit');
      const skippedCount = (html.match(/data-slot="constraint-skipped"/g) || []).length;
      expect(skippedCount).toBe(2);
      expect(html).toContain('Limit Unknown (Skipped)');
    });

    it('handles skipped flag set to true even with numeric limit_value', () => {
      const constraints: DeliberationConstraint[] = [
        {
          id: 'explicitly_skipped',
          unit: 'units',
          limit_value: 500,
          total_claimed: 100,
          skipped: true,
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['agent-a']} shared_constraints={constraints} />);
      expect(html).toContain('explicitly_skipped');
      expect(html).toContain('data-slot="constraint-skipped"');
      expect(html).not.toContain('Within limit');
    });

    it('handles skipped constraint via skipped_constraints panel array', () => {
      const constraints: DeliberationConstraint[] = [
        {
          id: 'listed_in_skipped_array',
          unit: 'calls',
          limit_value: 100,
          total_claimed: 10,
        },
      ];

      const html = renderToString(
        <DeliberationRoundtable
          agents={['agent-a']}
          shared_constraints={constraints}
          skipped_constraints={['listed_in_skipped_array']}
        />
      );
      expect(html).toContain('data-slot="constraint-skipped"');
    });

    it('handles missing description and limit_source gracefully', () => {
      const constraints: DeliberationConstraint[] = [
        {
          id: 'minimal_constraint',
          unit: 'ops',
          limit_value: 10,
          limit_source: null,
          description: undefined,
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['agent-a']} shared_constraints={constraints} />);
      expect(html).toContain('minimal_constraint');
      expect(html).toContain('ops');
      expect(html).toContain('Within limit');
    });
  });

  describe('4. Taint Propagation & Badge Rendering', () => {
    it('renders taint badge when tainted is true', () => {
      const proposals: DeliberationSpecialistProposal[] = [
        {
          agent_id: 'agent-untrusted',
          round_num: 1,
          summary: 'Untrusted input proposal',
          tainted: true,
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['agent-untrusted']} proposals={proposals} />);
      expect(html).toContain('data-slot="taint-badge"');
      expect(html).toContain('⚠️ Untrusted Source');
    });

    it('does NOT render taint badge when tainted is false or undefined', () => {
      const proposals: DeliberationSpecialistProposal[] = [
        {
          agent_id: 'agent-trusted-1',
          round_num: 1,
          summary: 'Trusted proposal with explicit false',
          tainted: false,
        },
        {
          agent_id: 'agent-trusted-2',
          round_num: 1,
          summary: 'Trusted proposal with undefined tainted',
          tainted: undefined,
        },
      ];

      const html = renderToString(
        <DeliberationRoundtable agents={['agent-trusted-1', 'agent-trusted-2']} proposals={proposals} />
      );
      expect(html).not.toContain('data-slot="taint-badge"');
      expect(html).not.toContain('⚠️ Untrusted Source');
    });
  });

  describe('5. Render Edge Cases & Text Robustness', () => {
    it('handles massive proposal texts and special characters without breaking', () => {
      const largeText = 'A'.repeat(10000) + ' <script>alert("xss")</script> & "quotes" \'apostrophes\'';
      const proposals: DeliberationSpecialistProposal[] = [
        {
          agent_id: 'agent-big',
          round_num: 1,
          summary: largeText,
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['agent-big']} proposals={proposals} />);
      expect(html).toContain('data-slot="proposal-card"');
      expect(html).not.toContain('<script>'); // Should be escaped by React
      expect(html).toContain('&lt;script&gt;');
    });

    it('handles missing recommendations, empty recommendations, and non-empty recommendations', () => {
      const proposals: DeliberationSpecialistProposal[] = [
        {
          agent_id: 'agent-empty-rec',
          round_num: 1,
          summary: 'No recommendations',
          recommendations: [],
        },
        {
          agent_id: 'agent-undefined-rec',
          round_num: 1,
          summary: 'Undefined recommendations',
          recommendations: undefined,
        },
        {
          agent_id: 'agent-valid-rec',
          round_num: 1,
          summary: 'Has recommendations',
          recommendations: ['Step 1', 'Step 2'],
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['agent-a']} proposals={proposals} />);
      expect(html).toContain('data-slot="recommendations"');
      expect(html).toContain('Step 1');
      expect(html).toContain('Step 2');
    });

    it('handles unusual or unknown termination_reason', () => {
      const reasons = ['converged', 'max_rounds', 'budget', 'cancelled', 'watchdog_timeout', 'custom_reason'];
      for (const reason of reasons) {
        const html = renderToString(
          <DeliberationRoundtable agents={['agent-a']} termination_reason={reason} />
        );
        expect(html).toContain('data-slot="panel-header"');
      }
    });

    it('handles staged actions with unknown risk tiers by failing closed to danger level', () => {
      const stagedActions: StagedActionItem[] = [
        {
          agent_id: 'agent-unknown',
          tool_name: 'custom_exotic_tool',
          risk_tier: 'unrecognized_tier' as any,
          rationale: 'Testing fail-closed tier mapping',
        },
        {
          agent_id: 'agent-undefined-tier',
          tool_name: 'mystery_tool',
          risk_tier: undefined as any,
        },
      ];

      const html = renderToString(
        <DeliberationRoundtable agents={['agent-unknown']} staged_actions={stagedActions} />
      );

      expect(html).toContain('data-slot="staged-actions"');
      // Both should have failed closed to danger
      const dangerCards = (html.match(/data-risk-level="danger"/g) || []).length;
      expect(dangerCards).toBe(2);
      expect(html).toContain('custom_exotic_tool');
      expect(html).toContain('mystery_tool');
    });

    it('handles minority reports with missing recommendations and empty proposed resolutions', () => {
      const minority: DeliberationMinorityReportItem[] = [
        {
          issue_type: 'custom_conflict',
          target_agent_id: 'agent-left',
          reviewer_agent_id: 'agent-right',
          target_position: 'Target perspective',
          target_recommendations: undefined,
          reviewer_critique: 'Reviewer critique text',
          reviewer_proposed_resolution: '',
        },
      ];

      const html = renderToString(
        <DeliberationRoundtable agents={['agent-left', 'agent-right']} minority_reports={minority} />
      );

      expect(html).toContain('data-slot="minority-report"');
      expect(html).toContain('data-slot="minority-option"');
      expect(html).toContain('Option A (agent-left Position)');
      expect(html).toContain('Option B (agent-right Position)');
    });
  });

  describe('6. Disagree-or-Commit Stances & Critiques Resilience', () => {
    it('renders all standard stances (endorse, complement, amend, conflict)', () => {
      const critiques: DeliberationPeerCritique[] = [
        {
          reviewer_agent_id: 'r1',
          target_agent_id: 't1',
          round_num: 1,
          stance: 'endorse',
          issue_type: 'synergy',
          critique: 'Endorsed',
          proposed_resolution: 'None',
        },
        {
          reviewer_agent_id: 'r2',
          target_agent_id: 't2',
          round_num: 1,
          stance: 'complement',
          issue_type: 'coordination',
          critique: 'Complemented',
          proposed_resolution: 'Add step',
        },
        {
          reviewer_agent_id: 'r3',
          target_agent_id: 't3',
          round_num: 1,
          stance: 'amend',
          issue_type: 'tuning',
          critique: 'Amended',
          proposed_resolution: 'Tune param',
        },
        {
          reviewer_agent_id: 'r4',
          target_agent_id: 't4',
          round_num: 1,
          stance: 'conflict',
          issue_type: 'incompatibility',
          critique: 'Conflicted',
          proposed_resolution: 'Block execution',
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['r1', 't1']} critiques={critiques} />);
      expect(html).toContain('ENDORSE');
      expect(html).toContain('COMPLEMENT');
      expect(html).toContain('AMEND');
      expect(html).toContain('CONFLICT');
    });

    it('handles unexpected stance values without crashing', () => {
      const critiques: DeliberationPeerCritique[] = [
        {
          reviewer_agent_id: 'r-custom',
          target_agent_id: 't-custom',
          round_num: 1,
          stance: 'inconclusive' as any,
          issue_type: 'unknown_type',
          critique: 'Custom stance test',
          proposed_resolution: 'Investigate',
        },
      ];

      const html = renderToString(<DeliberationRoundtable agents={['r-custom']} critiques={critiques} />);
      expect(html).toContain('INCONCLUSIVE');
      expect(html).toContain('Custom stance test');
    });

    it('tests behavior when stance is undefined or null', () => {
      const critiques = [
        {
          reviewer_agent_id: 'r-null',
          target_agent_id: 't-null',
          round_num: 1,
          stance: undefined as any,
          issue_type: 'unknown',
          critique: 'No stance critique',
          proposed_resolution: 'Resolution',
        },
      ];

      expect(() => {
        renderToString(<DeliberationRoundtable agents={['r-null']} critiques={critiques} />);
      }).toThrow(TypeError);
    });

    it('handles null entries in proposal record mapping', () => {
      const html = renderToString(
        <DeliberationRoundtable
          agents={['agent-a']}
          proposals={{
            1: null as any,
            2: {
              'agent-a': {
                agent_id: 'agent-a',
                round_num: 2,
                summary: 'P2',
              },
            },
          }}
          critiques={{
            1: null as any,
          }}
        />
      );
      expect(html).toContain('P2');
    });
  });

  describe('7. Data-Slot Invariants & Slot Integrity Under Stress', () => {
    it('preserves all root data-slot attributes under complete composite load', () => {
      const html = renderToString(
        <DeliberationRoundtable
          panel_id="panel-stress-99"
          title="Full Stress Load"
          agents={['agent-1', 'agent-2']}
          shared_constraints={[
            { id: 'c1', unit: 'mb', limit_value: 100, total_claimed: 50 },
            { id: 'c2', unit: 'cpu', limit_value: null },
          ]}
          proposals={[
            { agent_id: 'agent-1', round_num: 1, summary: 'P1' },
            { agent_id: 'agent-2', round_num: 2, summary: 'P2', tainted: true },
          ]}
          critiques={[
            {
              reviewer_agent_id: 'agent-2',
              target_agent_id: 'agent-1',
              round_num: 1,
              stance: 'amend',
              issue_type: 'res',
              critique: 'C1',
              proposed_resolution: 'R1',
            },
          ]}
          minority_reports={[
            {
              issue_type: 'res',
              target_agent_id: 'agent-1',
              reviewer_agent_id: 'agent-2',
              target_position: 'Pos1',
              reviewer_critique: 'Crit1',
              reviewer_proposed_resolution: 'Prop1',
            },
          ]}
          open_amendments={[
            {
              reviewer_agent_id: 'agent-2',
              target_agent_id: 'agent-1',
              round_num: 2,
              stance: 'amend',
              issue_type: 'res',
              critique: 'OpenCrit1',
              proposed_resolution: 'OpenProp1',
            },
          ]}
          staged_actions={[
            {
              agent_id: 'agent-1',
              tool_name: 'tool_a',
              risk_tier: 'write_local',
            },
          ]}
          converged={true}
          rounds_used={2}
        />
      );

      // Verify all contract data slots exist
      expect(html).toContain('data-slot="deliberation-roundtable"');
      expect(html).toContain('data-slot="panel-header"');
      expect(html).toContain('data-slot="title"');
      expect(html).toContain('data-slot="agent-pills"');
      expect(html).toContain('data-slot="agent-pill"');
      expect(html).toContain('data-slot="constraint-meters"');
      expect(html).toContain('data-slot="constraint-item"');
      expect(html).toContain('data-slot="constraint-skipped"');
      expect(html).toContain('data-slot="proposals-section"');
      expect(html).toContain('data-slot="proposals-header"');
      expect(html).toContain('data-slot="round-tabs"');
      expect(html).toContain('data-slot="proposal-card"');
      expect(html).toContain('data-slot="revision-badge"');
      expect(html).toContain('data-slot="taint-badge"');
      expect(html).toContain('data-slot="critiques-section"');
      expect(html).toContain('data-slot="critique-item"');
      expect(html).toContain('data-slot="stance-badge"');
      expect(html).toContain('data-slot="minority-report"');
      expect(html).toContain('data-slot="minority-option"');
      expect(html).toContain('data-slot="open-amendments"');
      expect(html).toContain('data-slot="staged-actions"');
      expect(html).toContain('data-slot="approval-card"');
    });
  });

  describe('8. Interactive DOM Behavior & Tab Filtering', () => {
    it('switches visible proposals and critiques when round tabs are clicked in DOM', async () => {
      const { createRoot } = await import('react-dom/client');
      const container = document.createElement('div');
      document.body.appendChild(container);
      const root = createRoot(container);

      const proposals: DeliberationSpecialistProposal[] = [
        { agent_id: 'agent-1', round_num: 1, summary: 'Proposal R1' },
        { agent_id: 'agent-1', round_num: 2, summary: 'Proposal R2' },
      ];
      const critiques: DeliberationPeerCritique[] = [
        {
          reviewer_agent_id: 'agent-2',
          target_agent_id: 'agent-1',
          round_num: 1,
          stance: 'endorse',
          issue_type: 'general',
          critique: 'Critique R1',
          proposed_resolution: 'Res R1',
        },
        {
          reviewer_agent_id: 'agent-2',
          target_agent_id: 'agent-1',
          round_num: 2,
          stance: 'amend',
          issue_type: 'general',
          critique: 'Critique R2',
          proposed_resolution: 'Res R2',
        },
      ];

      await React.act(async () => {
        root.render(
          <DeliberationRoundtable
            agents={['agent-1', 'agent-2']}
            proposals={proposals}
            critiques={critiques}
          />
        );
      });

      // Initially 'all' rounds are visible
      expect(container.textContent).toContain('Proposal R1');
      expect(container.textContent).toContain('Proposal R2');
      expect(container.textContent).toContain('Critique R1');
      expect(container.textContent).toContain('Critique R2');

      // Click Round 1 tab
      const round1Btn = Array.from(container.querySelectorAll('button[role="tab"]')).find(
        (b) => b.textContent?.trim() === 'Round 1'
      ) as HTMLButtonElement;
      expect(round1Btn).toBeDefined();

      await React.act(async () => {
        round1Btn.click();
      });

      // Now only Round 1 proposals and critiques should be visible
      expect(container.textContent).toContain('Proposal R1');
      expect(container.textContent).not.toContain('Proposal R2');
      expect(container.textContent).toContain('Critique R1');
      expect(container.textContent).not.toContain('Critique R2');

      // Click All Rounds tab
      const allRoundsBtn = Array.from(container.querySelectorAll('button[role="tab"]')).find(
        (b) => b.textContent?.trim() === 'All Rounds'
      ) as HTMLButtonElement;
      expect(allRoundsBtn).toBeDefined();

      await React.act(async () => {
        allRoundsBtn.click();
      });

      expect(container.textContent).toContain('Proposal R1');
      expect(container.textContent).toContain('Proposal R2');

      await React.act(async () => {
        root.unmount();
      });
      container.remove();
    });

    it('triggers onApproveStagedAction callback when approve button is clicked in DOM', async () => {
      const { createRoot } = await import('react-dom/client');
      const container = document.createElement('div');
      document.body.appendChild(container);
      const root = createRoot(container);

      const onApprove = vi.fn().mockResolvedValue(undefined);
      const stagedActions: StagedActionItem[] = [
        {
          id: 'action-test-1',
          agent_id: 'agent-1',
          tool_name: 'test_tool',
          risk_tier: 'write_local',
          status: 'pending',
        },
      ];

      await React.act(async () => {
        root.render(
          <DeliberationRoundtable
            agents={['agent-1']}
            staged_actions={stagedActions}
            onApproveStagedAction={onApprove}
          />
        );
      });

      const approveBtn = Array.from(container.querySelectorAll('button')).find(
        (b) => b.textContent?.includes('Approve')
      ) as HTMLButtonElement;
      expect(approveBtn).toBeDefined();

      await React.act(async () => {
        approveBtn.click();
        await new Promise((r) => setTimeout(r, 0));
      });

      expect(onApprove).toHaveBeenCalledWith('action-test-1', 'approved');

      await React.act(async () => {
        root.unmount();
      });
      container.remove();
    });
  });
});
