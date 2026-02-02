import React from 'react';

type AIActionCardProps = {
  title: string;
  description?: string;
  onClick?: () => void;
  icon?: React.ReactNode;
  disabled?: boolean;
};

export const AIActionCard: React.FC<AIActionCardProps> = ({ title, description, onClick, icon, disabled }) => (
  <button
    className="w-full bg-surface border border-gray-200 rounded-lg p-4 flex items-center gap-4 shadow hover:shadow-md transition disabled:opacity-60"
    onClick={onClick}
    disabled={disabled}
  >
    {icon && <span className="text-2xl">{icon}</span>}
    <div className="flex flex-col items-start text-left">
      <span className="font-semibold text-lg text-gray-900">{title}</span>
      {description && <span className="text-body-sm text-gray-600 mt-1">{description}</span>}
    </div>
  </button>
);
