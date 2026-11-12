/* Experimental RAM-only BIOS/Linux handoff for FAS2240-2 LOADER 4.3.
 * ELF64 container; CPU entry is 32-bit. Never accesses disks or flash.
 */
.code32
.section .text
.global _start
_start:
    cli
    cld
    mov $stack_top, %esp
    mov $entry_message, %esi
    call puts
    mov %cr0, %eax
    call hex32
    mov $newline, %esi
    call puts
    mov %cr0, %eax
    test $0x80000000, %eax
    jnz bad_state
    lgdt gdt_pointer
    ljmp $0x10, $flat32
flat32:
    mov $0x18, %ax
    mov %ax, %ds
    mov %ax, %es
    mov %ax, %fs
    mov %ax, %gs
    mov %ax, %ss
    mov $stack_top, %esp
    /* Read the existing UART divisor; restore its line-control register. */
    mov $0x3fb, %dx
    in %dx, %al
    mov %al, %bl
    or $0x80, %al
    out %al, %dx
    mov $0x3f9, %dx
    in %dx, %al
    mov %al, %bh
    mov $0x3f8, %dx
    in %dx, %al
    movzbl %al, %ecx
    movzbl %bh, %eax
    shl $8, %eax
    or %eax, %ecx
    mov $0x3fb, %dx
    mov %bl, %al
    out %al, %dx
    test %ecx, %ecx
    jz default_baud
    mov $115200, %eax
    xor %edx, %edx
    div %ecx
    jmp encode_baud
default_baud:
    mov $9600, %eax
encode_baud:
    mov $baud_digits+5, %edi
    mov $6, %ecx
    mov $10, %ebx
baud_loop:
    xor %edx, %edx
    div %ebx
    add $48, %dl
    mov %dl, (%edi)
    dec %edi
    loop baud_loop
    mov $baud_message, %esi
    call puts
    mov $baud_digits, %esi
    mov $6, %ecx
    call putn
    mov $newline, %esi
    call puts
    mov $setup_image, %esi
    mov $0x10000, %edi
    mov $setup_end-setup_image, %ecx
    rep movsb
    mov $protected_image, %esi
    mov $0x100000, %edi
    mov $protected_end-protected_image, %ecx
    rep movsb
    mov $initramfs_image, %esi
    mov $0x18000000, %edi
    mov $initramfs_end-initramfs_image, %ecx
    rep movsb
    mov $command_line, %esi
    mov $0x20000, %edi
    mov $command_end-command_line, %ecx
    rep movsb
    mov $trampoline_start, %esi
    mov $0x8000, %edi
    mov $trampoline_end-trampoline_start, %ecx
    rep movsb
    mov $handoff_message, %esi
    call puts
    /* The copied 16-bit stub transitions to BIOS real mode. */
    ljmp $0x20, $0x8000
bad_state:
    mov $bad_message, %esi
    call puts
halt:
    cli
    hlt
    jmp halt
puts:
    lodsb
    test %al, %al
    jz put_return
    call putc
    jmp puts
putn:
    lodsb
    call putc
    loop putn
put_return:
    ret
putc:
    push %ebx
    push %ecx
    push %edx
    mov %al, %bl
    mov $65536, %ecx
    mov $0x3fd, %dx
uart_wait:
    in %dx, %al
    test $0x20, %al
    jnz uart_send
    loop uart_wait
    jmp uart_done
uart_send:
    mov $0x3f8, %dx
    mov %bl, %al
    out %al, %dx
uart_done:
    pop %edx
    pop %ecx
    pop %ebx
    ret
hex32:
    push %eax
    push %ebx
    push %ecx
    mov %eax, %ebx
    mov $8, %ecx
hex_loop:
    rol $4, %ebx
    mov %ebx, %eax
    and $15, %al
    cmp $10, %al
    jb hex_digit
    add $39, %al
hex_digit:
    add $48, %al
    call putc
    loop hex_loop
    pop %ecx
    pop %ebx
    pop %eax
    ret

.balign 8
gdt:
    .quad 0
    .quad 0
    .quad 0x00cf9a000000ffff /* Linux BOOT_CS 0x10 */
    .quad 0x00cf92000000ffff /* Linux BOOT_DS 0x18 */
    .quad 0x00009a000000ffff /* 16-bit code, base 0 */
gdt_end:
gdt_pointer:
    .word gdt_end-gdt-1
    .long gdt

/* This byte sequence is copied to conventional RAM before use. */
trampoline_start:
.code16
    cli
    mov %cr0, %eax
    and $0xfffffffe, %eax
    mov %eax, %cr0
    ljmp $0, $(0x8000+real_mode-trampoline_start)
real_mode:
    xor %ax, %ax
    mov %ax, %ds
    mov %ax, %es
    mov %ax, %ss
    mov $0x7c00, %sp
    lidt (0x8000+real_idt-trampoline_start)
    mov $0x1000, %ax
    mov %ax, %ds
    mov %ax, %es
    mov %ax, %fs
    mov %ax, %gs
    mov %ax, %ss
    mov $0xe000, %sp
    /* Enter the kernel's native BIOS setup; it collects the real E820 map. */
    ljmp $0x1020, $0
real_idt:
    .word 0x3ff
    .long 0
trampoline_end:
.code32

.section .rodata
entry_message: .asciz "\r\nNETAPP_LINUX_WRAPPER32 CR0="
newline: .asciz "\r\n"
baud_message: .asciz "UART inherited baud="
handoff_message: .asciz "Kernel/initramfs prepared in RAM; entering Linux BIOS setup\r\n"
bad_message: .asciz "REFUSED: unexpected paged CPU entry; controller halted in RAM\r\n"

.section .data
command_line:
    .ascii "console=ttyS0,"
baud_digits:
    .ascii "000000"
    .ascii "n8 "
    .incbin "kernel-options.bin"
command_end:
.balign 16
setup_image: .incbin "setup.bin"
setup_end:
.balign 4096
protected_image: .incbin "protected.bin"
protected_end:
.balign 4096
initramfs_image: .incbin "initramfs.cpio.gz"
initramfs_end:

.section .bss
.balign 16
stack: .skip 16384
stack_top:
.section .note.GNU-stack,"",@progbits
