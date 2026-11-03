import { Redirect } from "expo-router";
import { useUserData } from "@/modules/userData";

export default function Page() {
    const { data, ready } = useUserData();
    if (!ready) return null;

    return <Redirect href={!data.onboarded ? "/onboarding" : data.authenticated ? "/home" : "/login/choose"} />;
}
