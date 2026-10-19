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

export type AvatarSize = 'sm' | 'md' | 'lg' | 'xl';
export type MemberColorSlot = '1' | '2' | '3' | '4' | '5';

export interface AvatarProps extends React.HTMLAttributes<HTMLDivElement> {
  src?: string | null;
  alt?: string;
  name?: string;
  size?: AvatarSize;
  colorSlot?: MemberColorSlot;
  children?: React.ReactNode;
}

const sizeStyles: Record<AvatarSize, string> = {
  sm: 'h-8 w-8 text-xs',
  md: 'h-10 w-10 text-sm',
  lg: 'h-12 w-12 text-base',
  xl: 'h-16 w-16 text-lg',
};

const memberColorStyles: Record<MemberColorSlot, string> = {
  '1': 'bg-member-1-bg text-member-1-fg',
  '2': 'bg-member-2-bg text-member-2-fg',
  '3': 'bg-member-3-bg text-member-3-fg',
  '4': 'bg-member-4-bg text-member-4-fg',
  '5': 'bg-member-5-bg text-member-5-fg',
};

export const Avatar: React.FC<AvatarProps> = ({
  src,
  alt = '',
  name,
  size = 'md',
  colorSlot = '1',
  children,
  className,
  ...props
}) => {
  const [hasError, setHasError] = React.useState(false);

  const initials = React.useMemo(() => {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }, [name]);

  const showImage = src && !hasError;

  return (
    <div
      data-slot="avatar"
      data-size={size}
      data-color-slot={colorSlot}
      className={cn(
        'yc-Avatar-root relative inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full font-medium select-none border border-border',
        sizeStyles[size],
        memberColorStyles[colorSlot],
        className
      )}
      {...props}
    >
      {children ? (
        children
      ) : showImage ? (
        <img
          src={src}
          alt={alt || name || 'Avatar'}
          onError={() => setHasError(true)}
          data-slot="avatar-image"
          className="yc-Avatar-image h-full w-full object-cover"
        />
      ) : (
        <span data-slot="avatar-fallback" className="yc-Avatar-fallback leading-none">
          {initials}
        </span>
      )}
    </div>
  );
};
Avatar.displayName = 'Avatar';

export interface AvatarImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {}

export const AvatarImage: React.FC<AvatarImageProps> = ({ className, alt = '', ...props }) => (
  <img
    data-slot="avatar-image"
    alt={alt}
    className={cn('yc-Avatar-image h-full w-full object-cover', className)}
    {...props}
  />
);
AvatarImage.displayName = 'AvatarImage';

export interface AvatarFallbackProps extends React.HTMLAttributes<HTMLSpanElement> {}

export const AvatarFallback: React.FC<AvatarFallbackProps> = ({ className, children, ...props }) => (
  <span
    data-slot="avatar-fallback"
    className={cn('yc-Avatar-fallback leading-none font-medium', className)}
    {...props}
  >
    {children}
  </span>
);
AvatarFallback.displayName = 'AvatarFallback';
