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
import type { ChatMessage, ChatAttachment, ChatSlotHooks } from './types.js';

export interface ChatConnectedProps {
  threadId: string;
  initialMessages?: ChatMessage[];
  slotHooks?: ChatSlotHooks;
  className?: string;
  onMessageSent?: (msg: ChatMessage) => void;
}

export function ChatConnected({
  threadId,
  initialMessages = [],
  slotHooks,
  className,
  onMessageSent,
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

      const data = await res.json();
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
    >
      <ChatThread />
      <ChatComposer />
    </ChatRoot>
  );
}
