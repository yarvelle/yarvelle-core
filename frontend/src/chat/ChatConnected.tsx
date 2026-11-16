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
import { Chat, ChatRoot, ChatThread, ChatComposer } from './Chat.js';
import type { ChatMessage, ChatAttachment, ChatSlotHooks, EntityChangedEvent } from './types.js';
import { parseSseChunk } from '../lib/sse/index.js';

export interface ChatConnectedProps {
  threadId: string;
  initialMessages?: ChatMessage[];
  slotHooks?: ChatSlotHooks;
  className?: string;
  onMessageSent?: (msg: ChatMessage) => void;
  onEntityChanged?: (event: EntityChangedEvent) => void;
}

export function ChatConnected({
  threadId,
  initialMessages = [],
  slotHooks,
  className,
  onMessageSent,
  onEntityChanged,
}: ChatConnectedProps) {
  const [messages, setMessages] = React.useState<ChatMessage[]>(initialMessages);
  const [loading, setLoading] = React.useState(false);

  const handleSendMessage = async (content: string, attachments?: ChatAttachment[]) => {
    const userMessage: ChatMessage = {
      id: Math.random().toString(36).substring(2, 9),
      role: 'user',
      content,
      createdAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
      attachments,
    };

    setMessages((prev) => [...prev, userMessage]);
    onMessageSent?.(userMessage);
    setLoading(true);

    try {
      const res = await fetch(`/api/v1/threads/${encodeURIComponent(threadId)}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content, attachments }),
      });

      if (!res.ok) {
        throw new Error(`Server returned status ${res.status}`);
      }

      const contentType = res.headers.get('content-type') || '';
      if (contentType.includes('event-stream') && res.body) {
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let assistantContent = '';
        let toolTraces: any[] | undefined = undefined;
        let executionPlan: any[] | undefined = undefined;
        let approval: any = undefined;

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          const chunk = decoder.decode(value, { stream: true });
          const parsed = parseSseChunk(chunk, buffer);
          buffer = parsed.remainingBuffer;

          for (const ev of parsed.events) {
            try {
              const evData = JSON.parse(ev.data);
              if (ev.event === 'token' || evData.type === 'token') {
                assistantContent += (evData.delta || '');
              } else if (ev.event === 'entity_changed' || evData.type === 'entity_changed') {
                onEntityChanged?.(evData as EntityChangedEvent);
              } else if (ev.event === 'approval_required' || evData.type === 'approval_required') {
                approval = evData;
              }
            } catch {
              // Non-JSON SSE event data
            }
          }
        }

        const assistantMessage: ChatMessage = {
          id: Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: assistantContent,
          createdAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          toolTraces,
          executionPlan,
          approval,
        };

        setMessages((prev) => [...prev, assistantMessage]);
      } else {
        const data = await res.json();
        if (data.entityChanged && onEntityChanged) {
          onEntityChanged(data.entityChanged);
        } else if (Array.isArray(data.events) && onEntityChanged) {
          for (const ev of data.events) {
            if (ev.type === 'entity_changed') {
              onEntityChanged(ev);
            }
          }
        }
        const assistantMessage: ChatMessage = {
          id: data.id || Math.random().toString(36).substring(2, 9),
          role: 'assistant',
          content: data.content || data.reply || '',
          createdAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
          toolTraces: data.toolTraces,
          executionPlan: data.executionPlan,
          approval: data.approval,
        };

        setMessages((prev) => [...prev, assistantMessage]);
      }
    } catch (err) {
      console.error('Failed to send message:', err);
      const errorMessage: ChatMessage = {
        id: Math.random().toString(36).substring(2, 9),
        role: 'system',
        content: 'Unable to connect to the assistant. Please try again.',
        createdAt: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        status: 'error',
      };
      setMessages((prev) => [...prev, errorMessage]);
    } finally {
      setLoading(false);
    }
  };

  return (
    <ChatRoot
      messages={messages}
      onSendMessage={handleSendMessage}
      loading={loading}
      slotHooks={slotHooks}
      className={className}
      onEntityChanged={onEntityChanged}
    >
      <ChatThread />
      <ChatComposer />
    </ChatRoot>
  );
}
