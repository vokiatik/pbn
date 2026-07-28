import { TextField } from "@mui/material";

type GuidanceFieldProps = {
    value: string;
    disabled?: boolean;
    onChange: (value: string) => void;
};

export function GuidanceField({ value, disabled = false, onChange }: GuidanceFieldProps) {
    return (
        <TextField
            label="Additional guidance"
            size="small"
            multiline
            minRows={3}
            value={value}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
            placeholder="Keep the face recognizable and make the background simpler."
            helperText="Write one or two direct sentences. Say what must stay recognizable, what should become simpler, and where."
            inputProps={{ maxLength: 1000 }}
        />
    );
}
