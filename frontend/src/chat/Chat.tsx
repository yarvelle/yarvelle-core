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
import { Button } from '../primitives/Button.js';
import { Avatar, AvatarFallback, AvatarImage } from '../primitives/Avatar.js';
import { EmptyState } from '../primitives/EmptyState.js';
import { ChatMarkdown } from './ChatMarkdown.js';
import { MessageToolbar } from './MessageToolbar.js';
import { ThinkingIndicator } from './ThinkingIndicator.js';
import { ApprovalCard } from './ApprovalCard.js';
import { ToolTraceCard } from './ToolTraceCard.js';
import { ExecutionPlanCard } from './ExecutionPlanCard.js';
import type {
  ChatMessage,
  ChatAttachment,
  ChatSlotHooks,
} from './types.js';

interface ChatContextValue {
  messages: ChatMessage[];
  onSendMessage: (content: string, attachments?: ChatAttachment[]) => Promise<void> | void;
  loading: boolean;
  activeAttachments: ChatAttachment[];
  setActiveAttachments: React.Dispatch<React.SetStateAction<ChatAttachment[]>>;
  slotHooks?: ChatSlotHooks;
}

const ChatContext = React.createContext<ChatContextValue | null>(null);

export function useChatContext() {
  const ctx = React.useContext(ChatContext);
  if (!ctx) throw new Error('Chat compound components must be rendered inside <Chat.Root>');
  return ctx;
}

// 1. Root
export interface ChatRootProps {
  messages: ChatMessage[];
  onSendMessage: (content: string, attachments?: ChatAttachment[]) => Promise<void> | void;
  loading?: boolean;
  slotHooks?: ChatSlotHooks;
  children: React.ReactNode;
  className?: string;
}

export function ChatRoot({
  messages,
  onSendMessage,
  loading = false,
  slotHooks,
  children,
  className,
}: ChatRootProps) {
  const [activeAttachments, setActiveAttachments] = React.useState<ChatAttachment[]>([]);

  return (
    <ChatContext.Provider
      value={{
        messages,
        onSendMessage,
        loading,
        activeAttachments,
        setActiveAttachments,
        slotHooks,
      }}
    >
      <div
        data-slot="chat-root"
        className={cn('yc-Chat-root flex flex-col h-full w-full bg-surface text-fg', className)}
      >
        {children}
      </div>
    </ChatContext.Provider>
  );
}

// 2. Thread
export interface ChatThreadProps {
  className?: string;
  emptyTitle?: string;
  emptyDescription?: string;
}

export function ChatThread({
  className,
  emptyTitle = 'How can I assist you today?',
  emptyDescription = 'Start a conversation by typing a message below.',
}: ChatThreadProps) {
  const { messages } = useChatContext();
  const threadEndRef = React.useRef<HTMLDivElement | null>(null);

  React.useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  return (
    <div
      data-slot="chat-thread"
      className={cn('yc-Chat-thread flex-1 overflow-y-auto p-4 space-y-4', className)}
    >
      {messages.length === 0 ? (
        <EmptyState title={emptyTitle} description={emptyDescription} className="h-full" />
      ) : (
        messages.map((msg) => <ChatMessageItem key={msg.id} message={msg} />)
      )}
      <div ref={threadEndRef} />
    </div>
  );
}

// 3. Message
export interface ChatMessageProps {
  message: ChatMessage;
  className?: string;
}

export function ChatMessageItem({ message, className }: ChatMessageProps) {
  const { slotHooks } = useChatContext();
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';

  if (slotHooks?.messageRenderer) {
    const custom = slotHooks.messageRenderer(message);
    if (custom) return <>{custom}</>;
  }

  return (
    <div
      data-slot="chat-message"
      data-role={message.role}
      className={cn(
        'yc-Chat-message group flex w-full gap-3',
        isUser ? 'justify-end' : 'justify-start',
        className
      )}
    >
      {!isUser && (
        <Avatar size="sm" className="mt-1">
          {message.avatarUrl ? (
            <AvatarImage src={message.avatarUrl} alt={message.authorName || 'Assistant'} />
          ) : (
            <AvatarFallback>{(message.authorName || 'AI').substring(0, 2).toUpperCase()}</AvatarFallback>
          )}
        </Avatar>
      )}

      <div
        className={cn(
          'flex flex-col max-w-[80%] gap-1.5',
          isUser ? 'items-end' : 'items-start'
        )}
      >
        <div className="flex items-center gap-2 text-xs text-fg-muted">
          <span className="font-semibold">{message.authorName || (isUser ? 'You' : 'Assistant')}</span>
          <span>{message.createdAt}</span>
        </div>

        <div
          data-slot="message-bubble"
          className={cn(
            'yc-Chat-bubble rounded-2xl px-4 py-2.5 shadow-1 text-sm leading-relaxed',
            isUser
              ? 'bg-primary text-primary-fg rounded-be-sm'
              : isSystem
              ? 'bg-surface-2 text-fg-muted border border-border'
              : 'bg-surface-2 text-fg rounded-bs-sm border border-border'
          )}
        >
          {message.reasoning && (
            <div className="mb-2">
              <ThinkingIndicator reasoning={message.reasoning} />
            </div>
          )}

          {isUser ? (
            <div className="whitespace-pre-wrap">{message.content}</div>
          ) : (
            <ChatMarkdown content={message.content} />
          )}

          {message.executionPlan && message.executionPlan.length > 0 && (
            <ExecutionPlanCard steps={message.executionPlan} />
          )}

          {message.toolTraces && message.toolTraces.length > 0 && (
            <div className="mt-2 space-y-1">
              {message.toolTraces.map((trace) => (
                <ToolTraceCard key={trace.id} trace={trace} />
              ))}
            </div>
          )}

          {message.approval && (
            <div className="mt-2">
              <ApprovalCard
                id={message.approval.id}
                level={message.approval.level}
                label={message.approval.label}
                details={message.approval.details}
                status={message.approval.status}
              />
            </div>
          )}
        </div>

        {!isUser && (
          <div className="opacity-0 group-hover:opacity-100 transition-opacity duration-fast">
            <MessageToolbar content={message.content} />
          </div>
        )}
      </div>

      {isUser && (
        <Avatar size="sm" className="mt-1">
          {message.avatarUrl ? (
            <AvatarImage src={message.avatarUrl} alt="User" />
          ) : (
            <AvatarFallback>ME</AvatarFallback>
          )}
        </Avatar>
      )}
    </div>
  );
}

// 4. Attachments Bar
export function ChatAttachments({ className }: { className?: string }) {
  const { activeAttachments, setActiveAttachments } = useChatContext();

  if (activeAttachments.length === 0) return null;

  return (
    <div
      data-slot="chat-attachments"
      className={cn('yc-Chat-attachments flex flex-wrap gap-2 px-4 py-2 bg-surface-2 border-t border-border', className)}
    >
      {activeAttachments.map((att) => (
        <div
          key={att.id}
          data-slot="attachment-item"
          className="yc-Chat-attachment flex items-center gap-1.5 rounded-md bg-surface px-2.5 py-1 text-xs border border-border shadow-1"
        >
          <span className="truncate max-w-[150px]">{att.name}</span>
          <button
            type="button"
            className="text-fg-muted hover:text-danger-fg"
            onClick={() =>
              setActiveAttachments((prev) => prev.filter((a) => a.id !== att.id))
            }
            aria-label={`Remove ${att.name}`}
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}

// 5. Composer
export interface ChatComposerProps {
  placeholder?: string;
  className?: string;
}

export function ChatComposer({
  placeholder = 'Type a message...',
  className,
}: ChatComposerProps) {
  const { onSendMessage, loading, activeAttachments, setActiveAttachments, slotHooks } =
    useChatContext();
  const [text, setText] = React.useState('');
  const fileInputRef = React.useRef<HTMLInputElement | null>(null);

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const trimmed = text.trim();
    if (!trimmed && activeAttachments.length === 0) return;
    if (loading) return;

    if (slotHooks?.beforeSend) {
      const result = await slotHooks.beforeSend(trimmed, activeAttachments);
      if (result === false) return;
      if (typeof result === 'string') {
        // Updated content
        await onSendMessage(result, activeAttachments);
        setText('');
        setActiveAttachments([]);
        return;
      }
    }

    await onSendMessage(trimmed, activeAttachments);
    setText('');
    setActiveAttachments([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files) return;
    const newAttachments: ChatAttachment[] = Array.from(files).map((f) => ({
      id: Math.random().toString(36).substring(2, 9),
      name: f.name,
      mimeType: f.type,
      sizeBytes: f.size,
    }));
    setActiveAttachments((prev) => [...prev, ...newAttachments]);
  };

  return (
    <form
      data-slot="chat-composer"
      onSubmit={handleSubmit}
      className={cn(
        'yc-Chat-composer flex flex-col gap-2 p-3 border-t border-border bg-surface',
        className
      )}
    >
      <ChatAttachments />

      <div className="flex items-end gap-2">
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFileChange}
        />

        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => fileInputRef.current?.click()}
          aria-label="Attach file"
          className="h-10 px-2.5 text-fg-muted"
        >
          📎
        </Button>

        {slotHooks?.composerAction}

        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          rows={1}
          className="flex-1 max-h-32 min-h-[44px] resize-none rounded-lg border border-border bg-surface-2 p-2.5 text-sm text-fg placeholder:text-fg-muted focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary"
          data-slot="input"
        />

        <Button
          type="submit"
          variant="primary"
          size="sm"
          disabled={loading || (!text.trim() && activeAttachments.length === 0)}
          loading={loading}
          className="h-10 px-4"
        >
          Send
        </Button>
      </div>
    </form>
  );
}

// Compound Export
export const Chat = {
  Root: ChatRoot,
  Thread: ChatThread,
  Message: ChatMessageItem,
  Composer: ChatComposer,
  Attachments: ChatAttachments,
};
