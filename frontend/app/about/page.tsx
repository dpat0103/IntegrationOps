import { redirect } from "next/navigation";
export default function About() {
  redirect(
    (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000") + "/about",
  );
}
