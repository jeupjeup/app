import { Button, Dialog, Text } from "@/components/ui";
import { useUserData } from "@/modules/userData";

export default function ApiFeedback() {
    const { error, dismissError, refresh, loading, data } = useUserData();
    return <Dialog visible={!!error} onClose={dismissError} close>
        <Text accessibilityRole="alert" style={{ textAlign: "center", fontSize: 14 }}>{error}</Text>
        {data.authenticated && <Button disabled={loading} onPress={() => { void refresh(); }}>새로고침</Button>}
        <Button onPress={dismissError}>확인</Button>
    </Dialog>;
}
