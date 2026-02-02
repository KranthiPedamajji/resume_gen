import { redirect } from 'next/navigation';

export default function Home() {
  redirect('/resume-input');
  return null;
}
