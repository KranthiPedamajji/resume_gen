import React from 'react';

type ScoreRingProps = {
  score: number; // 0-100
  size?: number;
};

export const ScoreRing: React.FC<ScoreRingProps> = ({ score, size = 128 }) => {
  const radius = size / 2 - 10;
  const circumference = 2 * Math.PI * radius;
  const progress = Math.max(0, Math.min(100, score));
  const offset = circumference - (progress / 100) * circumference;
  let color = '#16A34A'; // green
  if (score < 60) color = '#DC2626'; // red
  else if (score < 80) color = '#F59E0B'; // amber

  return (
    <svg width={size} height={size} className="block">
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        stroke="#D1D5DB"
        strokeWidth={10}
        fill="none"
      />
      <circle
        cx={size / 2}
        cy={size / 2}
        r={radius}
        stroke={color}
        strokeWidth={10}
        fill="none"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        style={{ transition: 'stroke-dashoffset 0.5s' }}
      />
      <text
        x="50%"
        y="50%"
        textAnchor="middle"
        dy=".3em"
        fontSize={size / 4}
        fontWeight="bold"
        fill={color}
      >
        {score}%
      </text>
    </svg>
  );
};
