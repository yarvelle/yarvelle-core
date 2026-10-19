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
import { CodeBlock } from './CodeBlock.js';
import { MermaidDiagram } from './MermaidDiagram.js';

export interface ChatMarkdownProps {
  content: string;
  className?: string;
}

export function ChatMarkdown({ content, className }: ChatMarkdownProps) {
  // Parse blocks: code fences ```lang ... ``` vs normal markdown paragraphs
  const blocks = React.useMemo(() => {
    const lines = content.split('\n');
    const result: Array<{ type: 'text' | 'code' | 'mermaid'; content: string; lang?: string }> = [];
    let currentCode: string[] = [];
    let currentLang = '';
    let inCode = false;
    let currentText: string[] = [];

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.startsWith('```')) {
        if (inCode) {
          // Closing fence
          const codeString = currentCode.join('\n');
          if (currentLang === 'mermaid') {
            result.push({ type: 'mermaid', content: codeString });
          } else {
            result.push({ type: 'code', content: codeString, lang: currentLang });
          }
          currentCode = [];
          currentLang = '';
          inCode = false;
        } else {
          // Opening fence
          if (currentText.length > 0) {
            result.push({ type: 'text', content: currentText.join('\n') });
            currentText = [];
          }
          inCode = true;
          currentLang = line.replace('```', '').trim();
        }
      } else if (inCode) {
        currentCode.push(line);
      } else {
        currentText.push(line);
      }
    }

    if (inCode && currentCode.length > 0) {
      result.push({ type: 'code', content: currentCode.join('\n'), lang: currentLang });
    } else if (currentText.length > 0) {
      result.push({ type: 'text', content: currentText.join('\n') });
    }

    return result;
  }, [content]);

  return (
    <div
      data-slot="chat-markdown"
      className={cn('yc-ChatMarkdown-root text-sm text-fg space-y-2 leading-relaxed', className)}
    >
      {blocks.map((b, idx) => {
        if (b.type === 'code') {
          return <CodeBlock key={idx} code={b.content} language={b.lang} />;
        }
        if (b.type === 'mermaid') {
          return <MermaidDiagram key={idx} chart={b.content} />;
        }
        return (
          <div key={idx} className="whitespace-pre-wrap">
            {b.content}
          </div>
        );
      })}
    </div>
  );
}
