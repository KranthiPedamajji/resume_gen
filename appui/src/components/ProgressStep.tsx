import React from 'react';

type ProgressStepProps = {
  steps: string[];
  current: number;
};

export const ProgressStep: React.FC<ProgressStepProps> = ({ steps, current }) => (
  <ol className="flex gap-4 items-center">
    {steps.map((step, idx) => (
      <li key={step} className="flex items-center gap-2">
        <span
          className={
            idx < current
              ? 'w-4 h-4 rounded-full bg-success'
              : idx === current
              ? 'w-4 h-4 rounded-full bg-primary animate-pulse'
              : 'w-4 h-4 rounded-full bg-gray-300'
          }
        ></span>
        <span className={idx === current ? 'font-semibold text-primary' : 'text-gray-500'}>{step}</span>
        {idx < steps.length - 1 && <span className="w-8 h-0.5 bg-gray-200 mx-2"></span>}
      </li>
    ))}
  </ol>
);
