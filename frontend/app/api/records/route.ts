import { NextRequest } from "next/server";
import { proxy } from "@/app/lib/gateway";

export async function GET(req: NextRequest) {
  const patientId = req.nextUrl.searchParams.get("patient_id") ?? "";
  // IDOR (intentional teaching point): the records view loads by a patient id
  // taken straight from the URL/input. The id is a sequential integer and the
  // backend performs NO ownership check — whatever id is passed is fetched.
  return proxy(req, `/patients/${encodeURIComponent(patientId)}/records`);
}
