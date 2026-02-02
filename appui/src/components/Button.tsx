import React from 'react';
import clsx from 'clsx';

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'danger';
  size?: 'sm' | 'md' | 'lg';
  loading?: boolean;
};

export const Button: React.FC<ButtonProps> = ({
  variant = 'primary',
  size = 'md',
  loading = false,
  className,
  children,
  ...props
}) => {
  return (
    <button
      className={clsx(
        'rounded-lg font-semibold transition focus:outline-none focus:ring-2 focus:ring-primary',
        {
          'bg-primary text-white hover:bg-primary-dark': variant === 'primary',
          'bg-gray-100 text-primary hover:bg-gray-200 border border-primary': variant === 'secondary',
          'bg-error text-white hover:bg-red-700': variant === 'danger',
          'px-4 py-2 text-base': size === 'md',
          'px-3 py-1.5 text-sm': size === 'sm',
          'px-6 py-3 text-lg': size === 'lg',
          'opacity-60 cursor-not-allowed': loading || props.disabled,
        },
        className
      )}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading ? <span className="loader mr-2"></span> : null}
      {children}
    </button>
  );
};
