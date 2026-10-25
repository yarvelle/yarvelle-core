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

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import * as React from 'react';
import { createRoot } from 'react-dom/client';
import { act } from 'react';

// Configure React 19 act environment in happy-dom
// @ts-ignore
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
import {
  DeliberationRoundtable,
  RoundtableCard,
  type DeliberationRoundtableProps,
  type DeliberationSpecialistProposal,
  type DeliberationPeerCritique,
  type DeliberationMinorityReportItem,
  type StagedActionItem,
} from '../src/index.js';

describe('DeliberationRoundtable & ApprovalCard Empirical Behavioral Suite', () => {
  let container: HTMLDivElement;
  let root: ReturnType<typeof createRoot>;

  beforeEach(() => {
    container = document.createElement('div');
    document.body.appendChild(container);
    root = createRoot(container);
  });

  afterEach(() => {
    act(() => {
      root.unmount();
    });
    container.remove();
    vi.restoreAllMocks();
  });

  const renderComponent = async (element: React.ReactElement) => {
    await act(async () => {
      root.render(element);
    });
  };

  // --------------------------------------------------------------------------
  // 1. Staged Action Approval Interactions & Callback Pass-Through
  // --------------------------------------------------------------------------
  describe('Staged Action Approval Interactions', () => {
    it('executes onApproveStagedAction callback with "approved" decision', async () => {
      const onApprove = vi.fn().mockImplementation(() => Promise.resolve());
      const stagedActions: StagedActionItem[] = [
        {
          id: 'action-test-1',
          agent_id: 'agent-executor',
          tool_name: 'dispatch_batch',
          tool_args: { batch_size: 50 },
          rationale: 'Execute scheduled batch run',
          risk_tier: 'write_local',
          status: 'pending',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-executor']}
          staged_actions={stagedActions}
          onApproveStagedAction={onApprove}
        />
      );

      const approvalCard = container.querySelector('[data-slot="approval-card"]');
      expect(approvalCard).not.toBeNull();

      // Find Approve button
      const buttons = container.querySelectorAll<HTMLButtonElement>('[data-slot="actions"] button');
      expect(buttons.length).toBe(2);
      const approveBtn = buttons[1]; // "Approve & Continue"
      expect(approveBtn.textContent).toContain('Approve & Continue');

      // Click Approve
      await act(async () => {
        approveBtn.click();
      });

      expect(onApprove).toHaveBeenCalledTimes(1);
      expect(onApprove).toHaveBeenCalledWith('action-test-1', 'approved');

      // Post-decision state: actions removed, status badge displayed
      expect(container.querySelector('[data-slot="actions"]')).toBeNull();
      expect(container.textContent).toContain('Approved');
    });

    it('executes onApproveStagedAction callback with "rejected" decision', async () => {
      const onApprove = vi.fn().mockImplementation(() => Promise.resolve());
      const stagedActions: StagedActionItem[] = [
        {
          id: 'action-test-2',
          agent_id: 'agent-sync',
          tool_name: 'delete_remote_cache',
          tool_args: { partition: 'p-01' },
          rationale: 'Purge remote partition',
          risk_tier: 'irreversible',
          status: 'pending',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-sync']}
          staged_actions={stagedActions}
          onApproveStagedAction={onApprove}
        />
      );

      const buttons = container.querySelectorAll<HTMLButtonElement>('[data-slot="actions"] button');
      const rejectBtn = buttons[0]; // "Reject"
      expect(rejectBtn.textContent).toContain('Reject');

      await act(async () => {
        rejectBtn.click();
      });

      expect(onApprove).toHaveBeenCalledTimes(1);
      expect(onApprove).toHaveBeenCalledWith('action-test-2', 'rejected');

      // Post-decision state: actions removed, status badge displayed
      expect(container.querySelector('[data-slot="actions"]')).toBeNull();
      expect(container.textContent).toContain('Rejected');
    });

    it('manages disabled states and loading spinner during in-flight decision', async () => {
      let resolvePromise!: () => void;
      const deferredPromise = new Promise<void>((resolve) => {
        resolvePromise = resolve;
      });
      const onApprove = vi.fn().mockReturnValue(deferredPromise);

      const stagedActions: StagedActionItem[] = [
        {
          id: 'action-async',
          agent_id: 'agent-async',
          tool_name: 'export_metrics',
          risk_tier: 'write_external',
          status: 'pending',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-async']}
          staged_actions={stagedActions}
          onApproveStagedAction={onApprove}
        />
      );

      const buttons = container.querySelectorAll<HTMLButtonElement>('[data-slot="actions"] button');
      const rejectBtn = buttons[0];
      const approveBtn = buttons[1];

      // Initiate approval
      let clickPromise: Promise<void>;
      act(() => {
        approveBtn.click();
      });

      // Verify buttons are disabled during loading
      expect(rejectBtn.disabled).toBe(true);
      expect(approveBtn.disabled).toBe(true);
      expect(approveBtn.getAttribute('data-loading')).toBe('true');
      expect(approveBtn.querySelector('[data-slot="spinner"]')).not.toBeNull();

      // Resolve the decision
      await act(async () => {
        resolvePromise();
      });

      // After resolution, actions area is gone and card is marked approved
      expect(container.querySelector('[data-slot="actions"]')).toBeNull();
      expect(container.textContent).toContain('Approved');
    });

    it('falls back to default API endpoint fetch when onApproveStagedAction is omitted', async () => {
      const mockFetch = vi.fn().mockResolvedValue({
        ok: true,
        json: async () => ({ status: 'approved' }),
      });
      vi.stubGlobal('fetch', mockFetch);

      const stagedActions: StagedActionItem[] = [
        {
          id: 'act-auto-fetch',
          agent_id: 'agent-fetch',
          tool_name: 'read_resource',
          risk_tier: 'read',
          status: 'pending',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-fetch']}
          staged_actions={stagedActions}
        />
      );

      const buttons = container.querySelectorAll<HTMLButtonElement>('[data-slot="actions"] button');
      const approveBtn = buttons[1];

      await act(async () => {
        approveBtn.click();
      });

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(mockFetch).toHaveBeenCalledWith(
        '/api/v1/approvals/act-auto-fetch/decide',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ decision: 'approved' }),
        })
      );
    });

    it('documents binary decision model: ApprovalCard does not offer "modify" action (ADR §2.7 invariant)', async () => {
      // In ADR-0001 §2.7: "Approvals bind to the exact staged tool name and arguments."
      // Deliberation approvals are strictly binary: approve or reject.
      // There is no UI button or method for in-flight argument tampering/modification.
      const stagedActions: StagedActionItem[] = [
        {
          id: 'action-binary',
          agent_id: 'agent-core',
          tool_name: 'apply_patch',
          tool_args: { file: 'config.json', patch_id: 'p1' },
          risk_tier: 'write_local',
          status: 'pending',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-core']}
          staged_actions={stagedActions}
        />
      );

      const buttons = Array.from(container.querySelectorAll<HTMLButtonElement>('[data-slot="actions"] button'));
      const buttonLabels = buttons.map((b) => b.textContent?.trim());

      expect(buttonLabels).toEqual(['Reject', 'Approve & Continue']);
      expect(buttonLabels.some((l) => l?.toLowerCase().includes('modify'))).toBe(false);
    });

    it('handles pre-resolved status (approved / rejected) without rendering action buttons', async () => {
      const stagedActions: StagedActionItem[] = [
        {
          id: 'action-already-approved',
          agent_id: 'agent-1',
          tool_name: 'backup_state',
          risk_tier: 'write_local',
          status: 'approved',
        },
        {
          id: 'action-already-rejected',
          agent_id: 'agent-2',
          tool_name: 'delete_segment',
          risk_tier: 'irreversible',
          status: 'rejected',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-1', 'agent-2']}
          staged_actions={stagedActions}
        />
      );

      const cards = container.querySelectorAll('[data-slot="approval-card"]');
      expect(cards.length).toBe(2);

      expect(cards[0].querySelector('[data-slot="actions"]')).toBeNull();
      expect(cards[0].textContent).toContain('Approved');

      expect(cards[1].querySelector('[data-slot="actions"]')).toBeNull();
      expect(cards[1].textContent).toContain('Rejected');
    });

    it('generates deterministic fallback id when action.id is undefined', async () => {
      const onApprove = vi.fn().mockImplementation(() => Promise.resolve());
      const stagedActions: StagedActionItem[] = [
        {
          // id intentionally omitted
          agent_id: 'agent-fallback',
          tool_name: 'reindex_catalog',
          risk_tier: 'write_local',
          status: 'pending',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-fallback']}
          staged_actions={stagedActions}
          onApproveStagedAction={onApprove}
        />
      );

      const buttons = container.querySelectorAll<HTMLButtonElement>('[data-slot="actions"] button');
      await act(async () => {
        buttons[1].click(); // Approve
      });

      expect(onApprove).toHaveBeenCalledTimes(1);
      expect(onApprove).toHaveBeenCalledWith('staged-agent-fallback-reindex_catalog-0', 'approved');
    });
  });

  // --------------------------------------------------------------------------
  // 2. Risk Tier Mapping & Fail-Closed Security Invariant
  // --------------------------------------------------------------------------
  describe('Risk Tier Mapping & Fail-Closed Security Invariant', () => {
    it('maps recognized risk tiers to proper design system levels', async () => {
      const stagedActions: StagedActionItem[] = [
        { id: '1', agent_id: 'a', tool_name: 't1', risk_tier: 'irreversible' },
        { id: '2', agent_id: 'a', tool_name: 't2', risk_tier: 'write_external' },
        { id: '3', agent_id: 'a', tool_name: 't3', risk_tier: 'write_local' },
        { id: '4', agent_id: 'a', tool_name: 't4', risk_tier: 'read' },
      ];

      await renderComponent(
        <DeliberationRoundtable agents={['a']} staged_actions={stagedActions} />
      );

      const cards = container.querySelectorAll('[data-slot="approval-card"]');
      expect(cards[0].getAttribute('data-risk-level')).toBe('danger');
      expect(cards[1].getAttribute('data-risk-level')).toBe('warn');
      expect(cards[2].getAttribute('data-risk-level')).toBe('warn');
      expect(cards[3].getAttribute('data-risk-level')).toBe('info');
    });

    it('fails closed to "danger" for unknown, empty, or missing risk tiers', async () => {
      const adversarialActions: any[] = [
        { id: 'adv-1', agent_id: 'a', tool_name: 't1', risk_tier: 'unknown_tier' },
        { id: 'adv-2', agent_id: 'a', tool_name: 't2', risk_tier: 'superadmin' },
        { id: 'adv-3', agent_id: 'a', tool_name: 't3', risk_tier: '' },
        { id: 'adv-4', agent_id: 'a', tool_name: 't4', risk_tier: undefined },
        { id: 'adv-5', agent_id: 'a', tool_name: 't5', risk_tier: null },
      ];

      await renderComponent(
        <DeliberationRoundtable agents={['a']} staged_actions={adversarialActions} />
      );

      const cards = container.querySelectorAll('[data-slot="approval-card"]');
      expect(cards.length).toBe(5);
      cards.forEach((card, idx) => {
        expect(card.getAttribute('data-risk-level')).toBe('danger');
      });
    });
  });

  // --------------------------------------------------------------------------
  // 3. Minority Report Edge Cases
  // --------------------------------------------------------------------------
  describe('Minority Report Edge Cases', () => {
    it('renders cleanly with multiline target positions, critiques, and resolutions', async () => {
      const minorityReports: DeliberationMinorityReportItem[] = [
        {
          issue_type: 'risk_exposure',
          target_agent_id: 'agent-proponent',
          reviewer_agent_id: 'agent-opponent',
          target_position: 'Paragraph 1: Primary rationale for data streaming.\n\nParagraph 2: Additional context on throughput.',
          target_recommendations: [
            'Line 1 of recommendation A\nContinuation line 2',
            'Line 2 of recommendation B',
          ],
          reviewer_critique: 'Adversarial critique:\n- Point 1: resource contention\n- Point 2: latency bounds',
          reviewer_proposed_resolution: 'Proposed resolution step 1;\nProposed resolution step 2.',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-proponent', 'agent-opponent']}
          minority_reports={minorityReports}
        />
      );

      const minoritySection = container.querySelector('[data-slot="minority-report"]');
      expect(minoritySection).not.toBeNull();

      const optionA = container.querySelector('[data-slot="minority-option"][data-option="A"]');
      const optionB = container.querySelector('[data-slot="minority-option"][data-option="B"]');

      expect(optionA).not.toBeNull();
      expect(optionB).not.toBeNull();

      expect(optionA?.textContent).toContain('Paragraph 1: Primary rationale');
      expect(optionA?.textContent).toContain('Paragraph 2: Additional context');
      expect(optionA?.textContent).toContain('Line 1 of recommendation A');

      expect(optionB?.textContent).toContain('Point 1: resource contention');
      expect(optionB?.textContent).toContain('Proposed resolution step 1');
    });

    it('renders safely when optional fields are empty strings or undefined', async () => {
      const minorityReports: DeliberationMinorityReportItem[] = [
        {
          issue_type: 'contraindication',
          target_agent_id: 'agent-a',
          reviewer_agent_id: 'agent-b',
          target_position: '',
          target_recommendations: undefined, // omitted
          reviewer_critique: '',
          reviewer_proposed_resolution: '',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-a', 'agent-b']}
          minority_reports={minorityReports}
        />
      );

      const optionA = container.querySelector('[data-slot="minority-option"][data-option="A"]');
      const optionB = container.querySelector('[data-slot="minority-option"][data-option="B"]');
      expect(optionA).not.toBeNull();
      expect(optionB).not.toBeNull();
      expect(optionA?.querySelector('ul')).toBeNull(); // No recommendations list rendered
    });

    it('renders multiple minority report conflict items', async () => {
      const minorityReports: DeliberationMinorityReportItem[] = [
        {
          issue_type: 'resource_overbudget',
          target_agent_id: 'agent-1',
          reviewer_agent_id: 'agent-2',
          target_position: 'Position 1',
          reviewer_critique: 'Critique 1',
          reviewer_proposed_resolution: 'Resolution 1',
        },
        {
          issue_type: 'dependency_order',
          target_agent_id: 'agent-3',
          reviewer_agent_id: 'agent-4',
          target_position: 'Position 2',
          reviewer_critique: 'Critique 2',
          reviewer_proposed_resolution: 'Resolution 2',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-1', 'agent-2', 'agent-3', 'agent-4']}
          minority_reports={minorityReports}
        />
      );

      const optionsA = container.querySelectorAll('[data-slot="minority-option"][data-option="A"]');
      const optionsB = container.querySelectorAll('[data-slot="minority-option"][data-option="B"]');
      expect(optionsA.length).toBe(2);
      expect(optionsB.length).toBe(2);
    });
  });

  // --------------------------------------------------------------------------
  // 4. Disagree-or-Commit Stance Transitions & Custom Issue Types
  // --------------------------------------------------------------------------
  describe('Disagree-or-Commit Stance Transitions', () => {
    it('renders all 4 standard stances with appropriate semantic badges', async () => {
      const critiques: DeliberationPeerCritique[] = [
        {
          reviewer_agent_id: 'r1',
          target_agent_id: 't1',
          round_num: 1,
          stance: 'endorse',
          issue_type: 'synergy',
          critique: 'Strong alignment with goals',
          proposed_resolution: 'Proceed as stated',
        },
        {
          reviewer_agent_id: 'r2',
          target_agent_id: 't2',
          round_num: 1,
          stance: 'complement',
          issue_type: 'dependency_order',
          critique: 'Can execute in parallel',
          proposed_resolution: 'Sequence alongside job 2',
        },
        {
          reviewer_agent_id: 'r3',
          target_agent_id: 't3',
          round_num: 1,
          stance: 'amend',
          issue_type: 'resource_overbudget',
          critique: 'Reduce buffer allocation',
          proposed_resolution: 'Cap buffer at 64MB',
        },
        {
          reviewer_agent_id: 'r4',
          target_agent_id: 't4',
          round_num: 1,
          stance: 'conflict',
          issue_type: 'risk_exposure',
          critique: 'Direct resource contention',
          proposed_resolution: 'Elect alternate coordinator',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable agents={['r1', 'r2', 'r3', 'r4']} critiques={critiques} />
      );

      const stanceBadges = container.querySelectorAll('[data-slot="stance-badge"]');
      expect(stanceBadges.length).toBe(4);

      expect(stanceBadges[0].textContent).toBe('ENDORSE');
      expect(stanceBadges[1].textContent).toBe('COMPLEMENT');
      expect(stanceBadges[2].textContent).toBe('AMEND');
      expect(stanceBadges[3].textContent).toBe('CONFLICT');
    });

    it('falls back cleanly to neutral badge for unexpected or custom stances', async () => {
      const customCritiques: any[] = [
        {
          reviewer_agent_id: 'r-custom',
          target_agent_id: 't-custom',
          round_num: 1,
          stance: 'abstain', // non-standard stance
          issue_type: 'custom_procedural_note',
          critique: 'Abstaining from vote due to domain boundary',
          proposed_resolution: 'Defer to secondary review',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable agents={['r-custom']} critiques={customCritiques} />
      );

      const stanceBadge = container.querySelector('[data-slot="stance-badge"]');
      expect(stanceBadge).not.toBeNull();
      expect(stanceBadge?.textContent).toBe('ABSTAIN');
      // Badge variant falls back to neutral
      expect(stanceBadge?.className).toContain('yc-Badge-root');
    });

    it('renders custom issue types without restriction', async () => {
      const critiques: DeliberationPeerCritique[] = [
        {
          reviewer_agent_id: 'r-arch',
          target_agent_id: 't-arch',
          round_num: 1,
          stance: 'amend',
          issue_type: 'io_pipeline_latency_threshold_exceeded',
          critique: 'I/O pipeline exceeds SLA',
          proposed_resolution: 'Add cache layer',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable agents={['r-arch']} critiques={critiques} />
      );

      expect(container.textContent).toContain('io_pipeline_latency_threshold_exceeded');
    });

    it('omits proposed resolution line when proposed_resolution is empty or absent', async () => {
      const critiques: any[] = [
        {
          reviewer_agent_id: 'r-no-res',
          target_agent_id: 't-no-res',
          round_num: 1,
          stance: 'endorse',
          issue_type: 'synergy',
          critique: 'Looks completely sound',
          proposed_resolution: '', // empty
        },
      ];

      await renderComponent(
        <DeliberationRoundtable agents={['r-no-res']} critiques={critiques} />
      );

      const critiqueItem = container.querySelector('[data-slot="critique-item"]');
      expect(critiqueItem?.textContent).not.toContain('Proposed:');
    });
  });

  // --------------------------------------------------------------------------
  // 5. Round Navigation Tabs & Proposal Filtering
  // --------------------------------------------------------------------------
  describe('Round Navigation Tabs & Proposal Filtering', () => {
    const multiRoundProposals: DeliberationSpecialistProposal[] = [
      {
        agent_id: 'agent-1',
        round_num: 1,
        summary: 'Proposal round 1 by agent 1',
      },
      {
        agent_id: 'agent-2',
        round_num: 1,
        summary: 'Proposal round 1 by agent 2',
      },
      {
        agent_id: 'agent-1',
        round_num: 2,
        summary: 'Proposal round 2 revision by agent 1',
      },
      {
        agent_id: 'agent-2',
        round_num: 3,
        summary: 'Proposal round 3 final by agent 2',
      },
    ];

    const multiRoundCritiques: DeliberationPeerCritique[] = [
      {
        reviewer_agent_id: 'agent-2',
        target_agent_id: 'agent-1',
        round_num: 1,
        stance: 'amend',
        issue_type: 'resource_overbudget',
        critique: 'Critique round 1',
        proposed_resolution: 'Resolution 1',
      },
      {
        reviewer_agent_id: 'agent-1',
        target_agent_id: 'agent-2',
        round_num: 2,
        stance: 'endorse',
        issue_type: 'synergy',
        critique: 'Critique round 2',
        proposed_resolution: 'Resolution 2',
      },
    ];

    it('does not render round tabs when only a single round exists', async () => {
      const singleRoundProposals: DeliberationSpecialistProposal[] = [
        {
          agent_id: 'agent-1',
          round_num: 1,
          summary: 'Single round proposal',
        },
      ];

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-1']}
          proposals={singleRoundProposals}
        />
      );

      expect(container.querySelector('[data-slot="round-tabs"]')).toBeNull();
    });

    it('renders round tabs in ascending order and filters proposals and critiques when switched', async () => {
      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-1', 'agent-2']}
          proposals={multiRoundProposals}
          critiques={multiRoundCritiques}
        />
      );

      const tabContainer = container.querySelector('[data-slot="round-tabs"]');
      expect(tabContainer).not.toBeNull();

      const tabs = Array.from(tabContainer!.querySelectorAll<HTMLButtonElement>('button'));
      const tabLabels = tabs.map((t) => t.textContent?.trim());
      expect(tabLabels).toEqual(['All Rounds', 'Round 1', 'Round 2', 'Round 3']);

      // Default: "All Rounds" selected
      expect(tabs[0].getAttribute('aria-selected')).toBe('true');
      expect(container.querySelectorAll('[data-slot="proposal-card"]').length).toBe(4);
      expect(container.querySelectorAll('[data-slot="critique-item"]').length).toBe(2);

      // 1. Switch to Round 1
      await act(async () => {
        tabs[1].click(); // "Round 1"
      });

      expect(tabs[1].getAttribute('aria-selected')).toBe('true');
      expect(tabs[0].getAttribute('aria-selected')).toBe('false');

      const r1Proposals = container.querySelectorAll('[data-slot="proposal-card"]');
      expect(r1Proposals.length).toBe(2);
      expect(container.textContent).toContain('Proposal round 1 by agent 1');
      expect(container.textContent).toContain('Proposal round 1 by agent 2');
      expect(container.textContent).not.toContain('Proposal round 2 revision');
      expect(container.textContent).not.toContain('Proposal round 3 final');

      const r1Critiques = container.querySelectorAll('[data-slot="critique-item"]');
      expect(r1Critiques.length).toBe(1);
      expect(container.textContent).toContain('Critique round 1');
      expect(container.textContent).not.toContain('Critique round 2');

      // 2. Switch to Round 2
      await act(async () => {
        tabs[2].click(); // "Round 2"
      });

      const r2Proposals = container.querySelectorAll('[data-slot="proposal-card"]');
      expect(r2Proposals.length).toBe(1);
      expect(container.textContent).toContain('Proposal round 2 revision by agent 1');

      const r2Critiques = container.querySelectorAll('[data-slot="critique-item"]');
      expect(r2Critiques.length).toBe(1);
      expect(container.textContent).toContain('Critique round 2');

      // 3. Switch to Round 3 (has proposal, no critique)
      await act(async () => {
        tabs[3].click(); // "Round 3"
      });

      const r3Proposals = container.querySelectorAll('[data-slot="proposal-card"]');
      expect(r3Proposals.length).toBe(1);
      expect(container.textContent).toContain('Proposal round 3 final by agent 2');
      expect(container.querySelector('[data-slot="critiques-section"]')).toBeNull(); // No critiques for round 3

      // 4. Switch back to "All Rounds"
      await act(async () => {
        tabs[0].click(); // "All Rounds"
      });

      expect(tabs[0].getAttribute('aria-selected')).toBe('true');
      expect(container.querySelectorAll('[data-slot="proposal-card"]').length).toBe(4);
      expect(container.querySelectorAll('[data-slot="critique-item"]').length).toBe(2);
    });

    it('correctly handles non-contiguous round numbers (e.g., Round 1 and Round 5)', async () => {
      const sparseProposals: DeliberationSpecialistProposal[] = [
        { agent_id: 'a1', round_num: 1, summary: 'Round 1 plan' },
        { agent_id: 'a1', round_num: 5, summary: 'Round 5 plan' },
      ];

      await renderComponent(
        <DeliberationRoundtable agents={['a1']} proposals={sparseProposals} />
      );

      const tabContainer = container.querySelector('[data-slot="round-tabs"]');
      const tabs = Array.from(tabContainer!.querySelectorAll<HTMLButtonElement>('button'));
      const labels = tabs.map((t) => t.textContent?.trim());
      expect(labels).toEqual(['All Rounds', 'Round 1', 'Round 5']);
    });
  });

  // --------------------------------------------------------------------------
  // 6. Memory Leaks, Event Listeners & Stress Resilience
  // --------------------------------------------------------------------------
  describe('Stability, Resource Management & Stress Resilience', () => {
    it('does not leak event listeners to window or document', async () => {
      const windowAddSpy = vi.spyOn(window, 'addEventListener');
      const docAddSpy = vi.spyOn(document, 'addEventListener');

      await renderComponent(
        <DeliberationRoundtable
          agents={['agent-1']}
          proposals={[{ agent_id: 'agent-1', round_num: 1, summary: 'Testing listeners' }]}
        />
      );

      expect(windowAddSpy).not.toHaveBeenCalled();
      expect(docAddSpy).not.toHaveBeenCalled();
    });

    it('mounts, unmounts, and remounts rapidly without throwing errors', async () => {
      for (let i = 0; i < 20; i++) {
        await renderComponent(
          <DeliberationRoundtable
            panel_id={`panel-stress-${i}`}
            agents={['agent-alpha']}
            staged_actions={[
              {
                id: `act-${i}`,
                agent_id: 'agent-alpha',
                tool_name: 'test_tool',
                risk_tier: 'read',
              },
            ]}
          />
        );
      }
      expect(container.textContent).toContain('panel-stress-19');
    });

    it('handles 100 rapid tab clicks without state desynchronization', async () => {
      const proposals: DeliberationSpecialistProposal[] = [
        { agent_id: 'a1', round_num: 1, summary: 'P1' },
        { agent_id: 'a1', round_num: 2, summary: 'P2' },
      ];

      await renderComponent(
        <DeliberationRoundtable agents={['a1']} proposals={proposals} />
      );

      const tabContainer = container.querySelector('[data-slot="round-tabs"]');
      const tabs = Array.from(tabContainer!.querySelectorAll<HTMLButtonElement>('button'));

      await act(async () => {
        for (let i = 0; i < 100; i++) {
          tabs[i % tabs.length].click();
        }
      });

      // 99 % 3 is 0 ("All Rounds")
      expect(tabs[0].getAttribute('aria-selected')).toBe('true');
      expect(container.querySelectorAll('[data-slot="proposal-card"]').length).toBe(2);
    });

    it('renders cleanly with entirely empty data structures', async () => {
      await renderComponent(
        <DeliberationRoundtable
          agents={[]}
          proposals={[]}
          critiques={[]}
          staged_actions={[]}
          shared_constraints={[]}
          minority_reports={[]}
          open_amendments={[]}
        />
      );

      expect(container.querySelector('[data-slot="deliberation-roundtable"]')).not.toBeNull();
      expect(container.querySelector('[data-slot="proposals-section"]')).toBeNull();
      expect(container.querySelector('[data-slot="critiques-section"]')).toBeNull();
      expect(container.querySelector('[data-slot="staged-actions"]')).toBeNull();
      expect(container.querySelector('[data-slot="minority-report"]')).toBeNull();
    });
  });
});
