import { Box, IconButton, Stack, Tooltip, Typography } from "@mui/material";
import type { ReactNode } from "react";

interface FieldHintProps {
    text?: string;
}

export function FieldHint({ text }: FieldHintProps) {
    if (!text) return null;

    return (
        <Tooltip
            arrow
            placement="right"
            enterTouchDelay={0}
            leaveTouchDelay={5000}
            title={
                <Typography
                    variant="caption"
                    sx={{
                        display: "block",
                        maxWidth: 320,
                        lineHeight: 1.45,
                    }}
                >
                    {text}
                </Typography>
            }
        >
            <IconButton
                type="button"
                size="small"
                aria-label="Parameter hint"
                sx={{
                    width: 28,
                    height: 28,
                    minWidth: 28,
                    flexShrink: 0,
                    color: "text.secondary",
                    border: "1px solid",
                    borderColor: "divider",
                    fontSize: 13,
                    fontWeight: 700,
                    lineHeight: 1,
                    "&:hover": {
                        color: "text.primary",
                        borderColor: "text.secondary",
                        backgroundColor: "action.hover",
                    },
                }}
            >
                ?
            </IconButton>
        </Tooltip>
    );
}

interface FieldWithHintProps {
    hint?: string;
    children: ReactNode;
}

export function FieldWithHint({ hint, children }: FieldWithHintProps) {
    return (
        <Stack
            direction="row"
            spacing={1}
            alignItems="center"
            sx={{ width: "100%" }}
        >
            <Box sx={{ flex: 1, minWidth: 0 }}>
                {children}
            </Box>

            <FieldHint text={hint} />
        </Stack>
    );
}