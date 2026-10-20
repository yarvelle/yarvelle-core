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

export interface SseEvent {
  event?: string;
  data: string;
  id?: string;
}

export function parseSseChunk(chunk: string, buffer: string = ''): { events: SseEvent[]; remainingBuffer: string } {
  const combined = buffer + chunk;
  const lines = combined.split(/\r?\n/);
  const events: SseEvent[] = [];

  let currentEvent: SseEvent = { data: '' };
  let hasData = false;

  // The last line might be incomplete if chunk ended mid-line
  const completeLines = lines.slice(0, -1);
  const remaining = lines[lines.length - 1];

  for (const line of completeLines) {
    if (line.trim() === '') {
      if (hasData) {
        events.push(currentEvent);
        currentEvent = { data: '' };
        hasData = false;
      }
      continue;
    }

    if (line.startsWith(':')) {
      // Comment / heartbeat line
      continue;
    }

    const colonIdx = line.indexOf(':');
    if (colonIdx === -1) {
      continue;
    }

    const field = line.slice(0, colonIdx).trim();
    const value = line.slice(colonIdx + 1).replace(/^\s/, '');

    if (field === 'event') {
      currentEvent.event = value;
    } else if (field === 'data') {
      currentEvent.data = currentEvent.data ? `${currentEvent.data}\n${value}` : value;
      hasData = true;
    } else if (field === 'id') {
      currentEvent.id = value;
    }
  }

  return { events, remainingBuffer: remaining };
}
