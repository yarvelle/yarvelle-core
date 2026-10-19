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

export type SheetSide = 'bottom' | 'start' | 'end';

interface SheetContextValue {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  side: SheetSide;
  sheetId: string;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
}

const SheetContext = React.createContext<SheetContextValue | null>(null);

function useSheetContext() {
  const context = React.useContext(SheetContext);
  if (!context) {
    throw new Error('Sheet compound components must be rendered within a <Sheet>');
  }
  return context;
}

export interface SheetProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  side?: SheetSide;
  children: React.ReactNode;
}

export function Sheet({
  open: controlledOpen,
  defaultOpen = false,
  onOpenChange,
  side = 'end',
  children,
}: SheetProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  const sheetId = React.useId();

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
    <SheetContext.Provider
      value={{
        open: isOpen,
        onOpenChange: handleOpenChange,
        side,
        sheetId,
        triggerRef,
      }}
    >
      {children}
    </SheetContext.Provider>
  );
}

export interface SheetTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  asChild?: boolean;
}

export const SheetTrigger = React.forwardRef<HTMLButtonElement, SheetTriggerProps>(
  ({ children, className, onClick, asChild = false, ...props }, ref) => {
    const { open, onOpenChange, sheetId, triggerRef } = useSheetContext();

    return (
      <button
        ref={(node) => {
          (triggerRef as React.MutableRefObject<HTMLButtonElement | null>).current = node;
          if (typeof ref === 'function') ref(node);
          else if (ref) ref.current = node;
        }}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={sheetId}
        data-slot="trigger"
        className={cn('yc-Sheet-trigger', className)}
        onClick={(e) => {
          onClick?.(e);
          if (!e.defaultPrevented) onOpenChange(!open);
        }}
        {...props}
      >
        {children}
      </button>
    );
  }
);
SheetTrigger.displayName = 'SheetTrigger';

const sideStyles: Record<SheetSide, string> = {
  end: 'inset-y-0 end-0 h-full w-3/4 max-w-md border-s border-border',
  start: 'inset-y-0 start-0 h-full w-3/4 max-w-md border-e border-border',
  bottom: 'inset-x-0 bottom-0 max-h-[85vh] border-t border-border rounded-t-xl',
};

export interface SheetContentProps extends React.HTMLAttributes<HTMLDivElement> {
  side?: SheetSide;
}

export const SheetContent = React.forwardRef<HTMLDivElement, SheetContentProps>(
  ({ children, className, side: propSide, ...props }, ref) => {
    const { open, onOpenChange, side: contextSide, sheetId, triggerRef } = useSheetContext();
    const side = propSide || contextSide;

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
      <div className="yc-Sheet-portal fixed inset-0 z-50 flex" data-slot="portal">
        <div
          className="yc-Sheet-overlay fixed inset-0 bg-overlay transition-opacity"
          data-slot="overlay"
          onClick={() => onOpenChange(false)}
          aria-hidden="true"
        />
        <div
          ref={ref}
          id={sheetId}
          role="dialog"
          aria-modal="true"
          data-slot="content"
          data-side={side}
          className={cn(
            'yc-Sheet-content fixed z-10 bg-surface p-6 shadow-3 text-fg transition-transform',
            sideStyles[side],
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
SheetContent.displayName = 'SheetContent';

export const SheetHeader: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  ...props
}) => (
  <div
    className={cn('yc-Sheet-header flex flex-col space-y-2 text-start pb-4', className)}
    data-slot="header"
    {...props}
  />
);
SheetHeader.displayName = 'SheetHeader';

export const SheetFooter: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  ...props
}) => (
  <div
    className={cn('yc-Sheet-footer flex flex-col-reverse sm:flex-row sm:justify-end sm:space-x-2 pt-4', className)}
    data-slot="footer"
    {...props}
  />
);
SheetFooter.displayName = 'SheetFooter';

export const SheetTitle: React.FC<React.HTMLAttributes<HTMLHeadingElement>> = ({
  className,
  ...props
}) => (
  <h2
    className={cn('yc-Sheet-title text-lg font-semibold text-fg', className)}
    data-slot="title"
    {...props}
  />
);
SheetTitle.displayName = 'SheetTitle';

export const SheetDescription: React.FC<React.HTMLAttributes<HTMLParagraphElement>> = ({
  className,
  ...props
}) => (
  <p
    className={cn('yc-Sheet-description text-sm text-fg-muted', className)}
    data-slot="description"
    {...props}
  />
);
SheetDescription.displayName = 'SheetDescription';

export const SheetClose: React.FC<React.ButtonHTMLAttributes<HTMLButtonElement>> = ({
  className,
  children,
  onClick,
  ...props
}) => {
  const { onOpenChange } = useSheetContext();
  return (
    <button
      type="button"
      className={cn('yc-Sheet-close', className)}
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
SheetClose.displayName = 'SheetClose';
