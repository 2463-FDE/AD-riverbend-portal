import Link from "next/link";

export default function Home() {
  return (
    <div>
      <h1>Welcome to Riverbend</h1>
      <p>Manage your care online.</p>
      <ul style={{ lineHeight: 2 }}>
        <li>
          <Link href="/register">New patient registration</Link>
        </li>
        <li>
          <Link href="/records">View my records</Link>
        </li>
      </ul>
    </div>
  );
}
