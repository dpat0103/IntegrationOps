import { redirect } from "next/navigation";
export default function Home() {
  redirect(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000");
}
