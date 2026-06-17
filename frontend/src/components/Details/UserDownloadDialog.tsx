import { Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, TextField } from "@mui/material";

type UserDownloadDialogProps = {
    open: boolean;
    email: string;
    username: string;
    phoneNumber: string;
    needMoreData: boolean;
    onClose: () => void;
    onSkip: () => void;
    onContinue: () => void;
    onSaveAndDownload: () => void;
    setEmail: (value: string) => void;
    setUsername: (value: string) => void;
    setPhoneNumber: (value: string) => void;
};

export function UserDownloadDialog({
    open,
    email,
    username,
    phoneNumber,
    needMoreData,
    onClose,
    onSkip,
    onContinue,
    onSaveAndDownload,
    setEmail,
    setUsername,
    setPhoneNumber,
}: UserDownloadDialogProps) {
    return (
        <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
            <DialogTitle>Before download, share contact info</DialogTitle>

            <DialogContent>
                <Stack spacing={2} mt={1}>
                    <TextField label="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />

                    {needMoreData && (
                        <>
                            <TextField label="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
                            <TextField label="Phone number" value={phoneNumber} onChange={(e) => setPhoneNumber(e.target.value)} />
                        </>
                    )}
                </Stack>
            </DialogContent>

            <DialogActions>
                <Button onClick={onSkip}>Skip</Button>

                {!needMoreData ? (
                    <Button variant="contained" onClick={onContinue}>Continue</Button>
                ) : (
                    <Button variant="contained" onClick={onSaveAndDownload}>Save and Download</Button>
                )}
            </DialogActions>
        </Dialog>
    );
}
