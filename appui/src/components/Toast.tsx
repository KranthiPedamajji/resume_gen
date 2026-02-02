import React from 'react';

type ToastProps = {
  message: string;
  type?: 'success' | 'error' | 'info';
};

export const Toast: React.FC<ToastProps> = ({ message, type = 'info' }) => {
  let color = 'bg-primary text-white';
  if (type === 'success') color = 'bg-success text-white';
  if (type === 'error') color = 'bg-error text-white';

  return (
    <div className={`fixed bottom-6 right-6 px-6 py-3 rounded-lg shadow-lg z-50 ${color}`}>
      {message}
    </div>
  );
};
