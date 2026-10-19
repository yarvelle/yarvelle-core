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

interface DialogContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  dialogId: string;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}

const DialogContext = React.createContext<DialogContextValue | null>(null);

function useDialogContext() {
  const context = React.useContext(DialogContext);
  if (!context) {
    throw new Error('Dialog compound components must be rendered within a <Dialog>');
  }
  return context;
}

export interface DialogProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}

export function Dialog({
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  children,
}: DialogProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  const dialogId = React.useId();

  const handleOpenChange = React.useCallback(
    (newOpen: boolean) => {
      if (!isControlled) {
        setUncontrolledOpen(newOpen);
      }
      onOpenChange?.(newOpen);
    },
    [isControlled, onOpenChange]
  );

  return (
    <DialogContext.Provider
      value={{
        open: isOpen,
        onOpenChange: handleOpenChange,
        dialogId,
        triggerRef,
      }}
    >
      {children}
    </DialogContext.Provider>
  );
}

export interface DialogTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean;
}

export const DialogTrigger = React.forwardRef<HTMLButtonElement, DialogTriggerProps>(
  ({ children, className, onClick, asChild = false, ...props }, ref) => {
    const { open, onOpenChange, dialogId, triggerRef } = useDialogContext();

    const setRef = React.useCallback(
      (node: HTMLButtonElement | null) => {
        (triggerRef as React.MutableRefObject<HTMLButtonElement | null>).current = node;
        if (typeof ref === 'function') {
          ref(node);
        } else if (ref) {
          ref.current = node;
        }
      },
      [ref, triggerRef]
    );

    return (
      <button
        ref={setRef}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={dialogId}
        data-slot="trigger"
        className={cn('yc-Dialog-trigger', className)}
        onClick={(e) => {
          onClick?.(e);
          if (!e.defaultPrevented) {
            onOpenChange(!open);
          }
        }}
        {...props}
      >
        {children}
      </button>
    );
  }
);
DialogTrigger.displayName = 'DialogTrigger';

export interface DialogContentProps extends React.HTMLAttributes<HTMLDivElement> {
  onCloseAutoFocus?: (event: Event) => void;
}

export const DialogContent = React.forwardRef<HTMLDivElement, DialogContentProps>(
  ({ children, className, ...props }, ref) => {
    const { open, onOpenChange, dialogId, triggerRef } = useDialogContext();
    const contentRef = React.useRef<HTMLDivElement | null>(null);

    React.useEffect(() => {
      if (!open) return;
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          onOpenChange(false);
          triggerRef.current?.focus();
        }
      };
      document.addEventListener('keydown', handleKeyDown);
      return () => document.removeEventListener('keydown', handleKeyDown);
    }, [open, onOpenChange, triggerRef]);

    if (!open) return null;

    return (
      <div
        className="yc-Dialog-portal fixed inset-0 z-50 flex items-center justify-center p-4"
        data-slot="portal"
      >
        <div
          className="yc-Dialog-overlay fixed inset-0 bg-overlay transition-opacity"
          data-slot="overlay"
          onClick={() => onOpenChange(false)}
          aria-hidden="true"
        />
        <div
          ref={(node) => {
            contentRef.current = node;
            if (typeof ref === 'function') ref(node);
            else if (ref) ref.current = node;
          }}
          id={dialogId}
          role="dialog"
          aria-modal="true"
          data-slot="content"
          className={cn(
            'yc-Dialog-content relative z-10 w-full max-w-lg rounded-xl bg-surface p-6 text-fg shadow-3 border border-border',
            'focus:outline-none',
            className
          )}
          {...props}
        >
          {children}
        </div>
      </div>
    );
  }
);
DialogContent.displayName = 'DialogContent';

export const DialogHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  ...props
}) => (
  <div
    className={cn('yc-Dialog-header flex flex-col space-y-1.5 text-start pb-4', className)}
    data-slot="header"
    {...props}
  />
);
DialogHeader.displayName = 'DialogHeader';

export const DialogFooter: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  ...props
}) => (
  <div
    className={cn('yc-Dialog-footer flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 pt-4', className)}
    data-slot="footer"
    {...props}
  />
);
DialogFooter.displayName = 'DialogFooter';

export const DialogTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>> = ({
  className,
  ...props
}) => (
  <h2
    className={cn('yc-Dialog-title text-lg font-semibold leading-none tracking-tight text-fg', className)}
    data-slot="title"
    {...props}
  />
);
DialogTitle.displayName = 'DialogTitle';

export const DialogDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>> = ({
  className,
  ...props
}) => (
  <p
    className={cn('yc-Dialog-description text-sm text-fg-muted', className)}
    data-slot="description"
    {...props}
  />
);
DialogDescription.displayName = 'DialogDescription';

export interface DialogCloseProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean;
}

export const DialogClose: React.FC<DialogCloseProps> = ({
  className,
  children,
  onClick,
  asChild = false,
  ...props
}) => {
  const { onOpenChange } = useDialogContext();
  return (
    <button
      type="button"
      className={cn('yc-Dialog-close', className)}
      data-slot="close"
      onClick={(e) => {
        onClick?.(e);
        if (!e.defaultPrevented) onOpenChange(false);
      }}
      {...props}
    >
      {children || 'Close'}
    </button>
  );
};
DialogClose.displayName = 'DialogClose';
