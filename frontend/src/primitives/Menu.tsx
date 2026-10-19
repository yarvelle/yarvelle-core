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

interface MenuContextValue {
  open: boolean;
  setOpen: (open: boolean) => void;
  triggerRef: React.RefObject<HTMLButtonElement | null>;
  menuId: string;
}

const MenuContext = React.createContext<MenuContextValue | null>(null);

function useMenuContext() {
  const ctx = React.useContext(MenuContext);
  if (!ctx) throw new Error('Menu compound components must be rendered inside <Menu>');
  return ctx;
}

export interface MenuProps {
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  children: React.ReactNode;
}

export function Menu({ open: controlledOpen, defaultOpen = false, onOpenChange, children }: MenuProps) {
  const [uncontrolledOpen, setUncontrolledOpen] = React.useState(defaultOpen);
  const isControlled = controlledOpen !== undefined;
  const isOpen = isControlled ? controlledOpen : uncontrolledOpen;
  const triggerRef = React.useRef<HTMLButtonElement | null>(null);
  const menuId = React.useId();

  const setOpen = React.useCallback(
    (next: boolean) => {
      if (!isControlled) setUncontrolledOpen(next);
      onOpenChange?.(next);
    },
    [isControlled, onOpenChange]
  );

  return (
    <MenuContext.Provider value={{ open: isOpen, setOpen, triggerRef, menuId }}>
      <div className="yc-Menu-root relative inline-block text-start" data-slot="root">
        {children}
      </div>
    </MenuContext.Provider>
  );
}

export interface MenuTriggerProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {}

export const MenuTrigger = React.forwardRef<HTMLButtonElement, MenuTriggerProps>(
  ({ children, className, onClick, ...props }, ref) => {
    const { open, setOpen, menuId, triggerRef } = useMenuContext();

    return (
      <button
        ref={(node) => {
          (triggerRef as React.MutableRefObject<HTMLButtonElement | null>).current = node;
          if (typeof ref === 'function') ref(node);
          else if (ref) ref.current = node;
        }}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={menuId}
        data-slot="trigger"
        className={cn('yc-Menu-trigger inline-flex items-center justify-center', className)}
        onClick={(e) => {
          onClick?.(e);
          if (!e.defaultPrevented) setOpen(!open);
        }}
        {...props}
      >
        {children}
      </button>
    );
  }
);
MenuTrigger.displayName = 'MenuTrigger';

export interface MenuContentProps extends React.HTMLAttributes<HTMLDivElement> {
  align?: 'start' | 'end' | 'center';
}

export const MenuContent = React.forwardRef<HTMLDivElement, MenuContentProps>(
  ({ children, className, align = 'start', ...props }, ref) => {
    const { open, setOpen, menuId, triggerRef } = useMenuContext();
    const contentRef = React.useRef<HTMLDivElement | null>(null);

    React.useEffect(() => {
      if (!open) return;
      const handleClickOutside = (e: MouseEvent) => {
        if (
          contentRef.current &&
          !contentRef.current.contains(e.target as Node) &&
          triggerRef.current &&
          !triggerRef.current.contains(e.target as Node)
        ) {
          setOpen(false);
        }
      };
      const handleKeyDown = (e: KeyboardEvent) => {
        if (e.key === 'Escape') {
          e.stopPropagation();
          setOpen(false);
          triggerRef.current?.focus();
        }
      };
      document.addEventListener('mousedown', handleClickOutside);
      document.addEventListener('keydown', handleKeyDown);
      return () => {
        document.removeEventListener('mousedown', handleClickOutside);
        document.removeEventListener('keydown', handleKeyDown);
      };
    }, [open, setOpen, triggerRef]);

    if (!open) return null;

    const alignClass =
      align === 'end' ? 'end-0' : align === 'center' ? 'start-1/2 -translate-x-1/2' : 'start-0';

    return (
      <div
        ref={(node) => {
          contentRef.current = node;
          if (typeof ref === 'function') ref(node);
          else if (ref) ref.current = node;
        }}
        id={menuId}
        role="menu"
        aria-orientation="vertical"
        tabIndex={-1}
        data-slot="content"
        className={cn(
          'yc-Menu-content absolute z-50 mt-1 min-w-[12rem] rounded-md bg-surface p-1 text-fg shadow-2 border border-border focus:outline-none',
          alignClass,
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);
MenuContent.displayName = 'MenuContent';

export interface MenuItemProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  destructive?: boolean;
}

export const MenuItem = React.forwardRef<HTMLButtonElement, MenuItemProps>(
  ({ children, className, destructive = false, onClick, disabled = false, ...props }, ref) => {
    const { setOpen } = useMenuContext();

    return (
      <button
        ref={ref}
        type="button"
        role="menuitem"
        tabIndex={-1}
        disabled={disabled}
        data-slot="item"
        data-destructive={destructive ? 'true' : undefined}
        className={cn(
          'yc-Menu-item group relative flex w-full cursor-pointer select-none items-center rounded-sm px-2.5 py-1.5 text-sm outline-none transition-colors duration-fast',
          'hover:bg-surface-2 focus:bg-surface-2',
          destructive
            ? 'text-danger-fg hover:bg-danger-bg focus:bg-danger-bg'
            : 'text-fg hover:text-fg',
          'disabled:pointer-events-none disabled:opacity-50',
          className
        )}
        onClick={(e) => {
          onClick?.(e);
          if (!e.defaultPrevented) setOpen(false);
        }}
        {...props}
      >
        {children}
      </button>
    );
  }
);
MenuItem.displayName = 'MenuItem';

export const MenuSeparator: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({ className, ...props }) => (
  <div
    role="separator"
    data-slot="separator"
    className={cn('yc-Menu-separator my-1 h-px bg-border', className)}
    {...props}
  />
);
MenuSeparator.displayName = 'MenuSeparator';
