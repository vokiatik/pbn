// src/components/common/FieldWithHint.tsx

import { Box, Stack } from "@mui/material";
import type { ReactNode } from "react";
import { FieldHint } from "./FieldHint";

interface FieldWithHintProps {
    hint?: string;
    children: ReactNode;
}

export function FieldWithHint({ hint, children }: FieldWithHintProps) {
    return (
        <Stack direction="row" spacing={1} alignItems="center">
            <Box sx={{ flex: 1 }}>
                {children}
            </Box>

            <FieldHint text={hint} />
        </Stack>
    );
}