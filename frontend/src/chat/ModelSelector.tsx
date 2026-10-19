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
import { Menu, MenuTrigger, MenuContent, MenuItem } from '../primitives/Menu.js';

export interface ModelOption {
  id: string;
  name: string;
  description?: string;
  provider?: string;
}

export interface ModelSelectorProps {
  models: ModelOption[];
  selectedModelId?: string;
  onSelectModel?: (modelId: string) => void;
  className?: string;
}

export function ModelSelector({
  models,
  selectedModelId,
  onSelectModel,
  className,
}: ModelSelectorProps) {
  const currentModel = models.find((m) => m.id === selectedModelId) || models[0];

  return (
    <div
      data-slot="model-selector"
      className={cn('yc-ModelSelector-root inline-block', className)}
    >
      <Menu>
        <MenuTrigger className="rounded-md border border-border bg-surface px-2.5 py-1 text-xs font-medium text-fg shadow-1 hover:bg-surface-2">
          <span className="me-1 text-fg-muted font-normal">Model:</span>
          <span>{currentModel ? currentModel.name : 'Select model'}</span>
          <span className="ms-1.5 text-fg-muted">▾</span>
        </MenuTrigger>
        <MenuContent align="start">
          {models.map((m) => (
            <MenuItem
              key={m.id}
              onClick={() => onSelectModel?.(m.id)}
              className={cn(m.id === currentModel?.id && 'font-semibold text-primary')}
            >
              <div className="flex flex-col text-start">
                <span>{m.name}</span>
                {m.provider && (
                  <span className="text-[10px] text-fg-muted font-normal">{m.provider}</span>
                )}
              </div>
            </MenuItem>
          ))}
        </MenuContent>
      </Menu>
    </div>
  );
}
